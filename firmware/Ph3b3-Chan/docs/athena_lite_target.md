# Athena as a valid Dio target (lite)

**Goal:** make a second Ph3b3 server (Athena, on WSL2) reachable so Dio can be repointed at it with a **portal edit only** — no firmware build. Dio already has the mechanism: an atomic NVS server record (`host`/`port`) editable from the Dio-Setup portal. This doc is the server-side checklist + the switch procedure.

**No firmware changes.** No creds in this doc — see `secrets.h` / `.env` for values.

---

## 1. Server checklist for Athena (WSL2 — the landmine)

WSL2's NAT is the whole difficulty: by default the Linux guest is on a private NAT and **not reachable from the LAN** (so Dio/phone can't hit it) even when uvicorn is bound correctly.

1. **Bind uvicorn to all interfaces:** `host=0.0.0.0`, `port=7331` (same as Nyx). Confirm inside WSL: `ss -tlnp | grep 7331` → `0.0.0.0:7331`.
2. **Make WSL reachable from the LAN — pick ONE:**
   - **Preferred: mirrored networking.** In Windows `%UserProfile%\.wslconfig`:
     ```
     [wsl2]
     networkingMode=mirrored
     ```
     then `wsl --shutdown` and restart. WSL now shares the Windows host's LAN IP — the server answers on the **Windows machine's** `192.168.x.x:7331`, stable across reboots.
   - **Fallback: `netsh` portproxy** (only if mirrored won't work): forward the Windows host port to the WSL IP:
     ```
     netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=7331 \
       connectaddress=<WSL_IP> connectport=7331
     ```
     ⚠️ **`<WSL_IP>` changes on every WSL reboot** — this proxy breaks each restart and must be re-pointed. This is exactly why **mirrored is strongly preferred**.
3. **Windows Firewall:** allow **inbound TCP 7331** (`New-NetFirewallRule -DisplayName "Ph3b3 7331" -Direction Inbound -Protocol TCP -LocalPort 7331 -Action Allow`). Without this, the phone/Dio get connection-refused even when everything else is right.

**Athena's LAN IP** = the **Windows host's** IP (mirrored) — find it on Windows with `ipconfig` (the Wi-Fi/Ethernet IPv4). Call it `<ATHENA_IP>` below.

---

## 2. Auth — the rule

Dio authenticates with the basic-auth user/pass baked in his NVS (seeded from `secrets.h`, currently matching **Nyx's** `.env`). So:

> **Rule: Athena's lite instance MUST use the SAME basic-auth user/pass as Nyx** (copy Nyx's `PH3B3_USER` / `PH3B3_PASSWORD` into Athena's `.env`).

Then switching Dio Nyx↔Athena is **host/port only** — no device auth reconfig. If Athena used different creds, Dio would reach it and show **`denied`** (the cause-diff status earns its keep here).

---

## 3. TLS — non-issue

Dio uses `WiFiClientSecure.setInsecure()`, so it does **not** validate the server cert. Athena can present any cert (its own mkcert, a different self-signed, whatever) and Dio connects fine. **Nothing to match on the TLS side.** (Athena must still serve **HTTPS** on 7331 — Dio speaks `https://`; a plain-HTTP server would fail the TLS handshake, showing `no route`.)

---

## 4. The switch procedure (for tired-you)

Repoint Dio between servers entirely from his captive portal:

1. **Raise the portal:** power-cycle Dio; when WiFi is joined but you want to reconfigure, trigger **Dio-Setup** (the portal also auto-raises if WiFi fails). Join the **`Dio-Setup`** AP from your phone → the form opens.
2. **Edit the Ph3b3 host/port fields** (they're pre-filled with the current target):
   - **→ Athena:** host = `<ATHENA_IP>`, port = `7331`
   - **→ Nyx:** host = `192.168.x.x`, port = `7331`
   - (WiFi fields: leave as-is unless the venue network changed.)
3. **Save** → Dio reboots, reads the NVS record, connects.
4. **Read his screen** (host/port + status are on-screen now):
   - Pointed at Nyx & healthy → **`online 192.168.x.x:7331`**
   - Pointed at Athena & healthy → **`online <ATHENA_IP>:7331`**
   - **`denied <ip>:7331`** → creds mismatch (fix §2 on that server)
   - **`no route <ip>:7331`** → can't reach it (fix §1: binding / mirrored / firewall)

---

## 5. Smoke-test order (phone first — the rule)

Always prove the server from a **phone on the same WiFi before touching Dio** — it isolates server/network problems from device problems (this is the rule that cracked the earlier Iris debugging):

1. **Phone → `https://<ATHENA_IP>:7331/health`** (accept the cert warning; self-signed).
   - **401** (auth-gated) or **200** = Athena is reachable → proceed.
   - **timeout / refused** = server not reachable → **stop and fix §1** (mirrored networking / firewall), do NOT touch Dio yet.
2. **Only then** repoint Dio (§4) and read his screen.

---

## Rails
- **Never push from Athena.** Git pushes originate from Nyx only; this doc is committed from Nyx with the rest of tonight's work.
- Multi-server **selection UI** / per-network profiles are **not** this — they stay in the Phase B design (`~/Arduino/Iris/docs/iris_config_sync_design.md`). Tonight, switching = a portal edit.
