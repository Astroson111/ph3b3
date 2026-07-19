# Rhea — backup & restore for Ph3b3

No single point of failure. If Nyx's SSD (or Nyx) dies, Phoebe's identity survives
on the external **RHEA** drive and restores onto any machine in under an hour.

> ## ⚠️ THE ENCRYPTION PASSPHRASE IS EVERYTHING
> The backups are encrypted (restic / AES-256). **Without the passphrase they are
> permanently unrecoverable — dead weight.** It is stored:
> - on Nyx at `~/.config/rhea/passphrase` (mode 600) so the nightly job runs unattended — **but that copy dies with the SSD**, and
> - **OFFLINE where the Captain chose** (paper / password vault). That offline copy is the one that saves you. Guard it.

## What it is
- **Tool:** [restic](https://restic.net) — a single static binary. A copy lives on the
  drive at `bin/restic`, so `restore.sh` runs on a bare machine with zero deps
  (borg would need Python+borg installed first — a bootstrapping hazard mid-disaster).
- **Drive:** ext4, label `RHEA`, UUID `dd7ef2c9-196c-4a15-ae8d-2c5a1dd9ef6f`, mounted
  `/mnt/rhea` via `/etc/fstab` **by UUID + `nofail`** (a missing drive never blocks Nyx's boot).
- **Repo:** `/mnt/rhea/restic` — encrypted, deduplicated. Retention **7 daily / 4 weekly / 6 monthly**, auto-pruned.
- **Schedule:** nightly at 03:30 via `rhea-backup.timer` (`Persistent=true` → runs a missed backup on next boot).

## What Rhea protects (the irreplaceable set)
- **Mnemosyne** + all SQLite DBs (`mnemosyne.db`, `argus.db`, `recipes.db`, Morpheus `generations.db`)
  — snapshotted via **`sqlite3 .backup`** (consistent; never a live-file copy mid-write).
- Soul (`soul/`), system-prompt/values/gating config (`config/`) — safety gating is
  **backed up read-only, never modified**.
- All configs, **`.env`** (secrets, not on GitHub), cadence contracts, device registry.
- Chat logs / transcripts (`chats/`), captures (photos + audio + sidecars).
- **Code lives on GitHub** (`ph3b3` @ `main`) — verified current; Rhea backs up data, not the repo.

**Skipped (re-downloadable bulk):** Ollama/Whisper/SDXL models, venvs, caches,
`sd_backup_16gb_*`, `RecipeNLG_code`, `edit_scratch`.

## Drive-missing behaviour (by design)
If RHEA isn't mounted at run time the backup **FAILS LOUDLY and exits non-zero** — it
**never** falls back to the internal SSD (that would fake safety on the disk that just
died). A failed/unplugged run sends no Argus heartbeat, so **`rhea` goes SILENT** on the
fleet panel within its 26h contract. Disk **> 80% used → `rhea` SICK** (space warning).
The watchtower (Argus) watches the ark — no new alert plumbing.

## Restore (manual only — never auto-runs)
On a fresh Ubuntu box with the RHEA drive attached — **run with `sudo`** (the backup
runs as root to capture `/etc/wireguard`, so the repo is root-owned; root also writes
`/etc/wireguard` + `/home` on restore):
```
sudo /mnt/rhea/restore.sh              # full restore to real locations
sudo /mnt/rhea/restore.sh --scratch /tmp/firedrill   # dry fire-drill, touches nothing live
```
A full restore chowns the recovered user data back to `astroson` at the end.
It prompts for the OFFLINE passphrase, restores the data + secrets + consistent SQLite
snapshots, then prints the remaining machine-specific steps (clone the code from GitHub,
`python -m venv` + `pip install`, `ollama pull` the models, re-link the systemd services).
Then `https://localhost:7331/panel` → "Made with Soul" greeting, Mnemosyne recall, gating active.

## Files (version-controlled in `ph3b3/deploy/rhea/`)
- `rhea-backup.sh` — the nightly job (sqlite snapshots → restic → prune → Argus heartbeat).
- `rhea-restore.sh` — restore (copied to the drive as `restore.sh`).
- `rhea-backup.service` / `rhea-backup.timer` — systemd units.
- `README.md` — this file (copied to the drive).

## Not in this PR (future Captain decision)
Offsite / rotated second drive. Rhea is **local only** — nothing leaves the building.
