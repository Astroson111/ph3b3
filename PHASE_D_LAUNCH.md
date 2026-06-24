# Phase D — Run Claude Code natively in WSL (Athena / ph3b3)

Goal: run `claude` as a native **Linux** process inside Ubuntu with `cwd = /home/lex_lson/ph3b3`,
eliminating the `wsl.exe` bridge (which mangles shell variables and adds CRLF/quoting friction).

## Why "just launch from WSL" is NOT enough (verified 2026-06-23)
- `which claude` in Ubuntu → `/mnt/c/Users/Alex Olson/AppData/Roaming/npm/claude`
  = the **Windows** install, visible in WSL only because Windows PATH is appended.
  Running it from the Ubuntu shell STILL produces a Windows process (reports `win32` / `MINGW64`). ❌
- **No native Node in WSL** (`node` not installed; `npm` resolves to `/mnt/c/Program Files/nodejs/npm`).
- **DNS broken in WSL**: `/etc/resolv.conf` is empty, `github.com` does not resolve.
  Blocks git, apt, curl, npm — must be fixed FIRST.
- `/etc/wsl.conf`: `systemd=true`, default user `lex_lson`, no `[network]` section.

---

## Prereq 0 — Fix WSL DNS (blocks everything else)
`/etc/resolv.conf` is empty. Stop WSL from auto-generating it, then set a static resolver:

```bash
# in Ubuntu
sudo tee -a /etc/wsl.conf >/dev/null <<'EOF'

[network]
generateResolvConf = false
EOF

sudo rm -f /etc/resolv.conf
printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' | sudo tee /etc/resolv.conf
```

Then from **Windows** (PowerShell/cmd): `wsl --shutdown`, reopen Ubuntu.
Verify: `getent hosts github.com`  → should print an IP.

## Prereq 1 — Install native Node in WSL (nvm, no sudo)
```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
exec $SHELL -l            # reload shell so nvm loads
nvm install --lts
which node                # MUST be /home/lex_lson/.nvm/...   (NOT /mnt/c/...)
node --version
```

## Prereq 2 — Install Claude Code natively in WSL
```bash
npm install -g @anthropic-ai/claude-code
which claude              # MUST be /home/lex_lson/.nvm/...   (NOT /mnt/c/...)
claude --version
```
If `which claude` still shows the `/mnt/c/...` Windows path, Windows PATH is shadowing the
Linux binary. Either ensure the nvm bin dir precedes Windows entries in PATH, or disable
Windows PATH interop in `/etc/wsl.conf`:
```ini
[interop]
appendWindowsPath = false
```
(then `wsl --shutdown` + reopen). Caveat: this removes the ability to call Windows .exe's
from the Ubuntu shell — only do it if you don't rely on that.

---

## Launch (the actual Phase D steps, once prereqs are done)
1. Open the Ubuntu shell — Start menu → "Ubuntu", or from Windows: `wsl ~ -d Ubuntu`.
2. `cd ~/ph3b3`
3. `claude`
4. Authenticate if prompted (first native run).

## Verify it's TRULY native (run inside the new session)
```bash
uname -a       # expect: Linux Athena ...      (NOT MINGW64 ... Msys)
echo $OSTYPE   # expect: linux-gnu             (NOT cygwin)
whoami         # expect: lex_lson              (NOT Alex Olson)
pwd            # expect: /home/lex_lson/ph3b3
which claude   # expect: /home/lex_lson/.nvm/...  (NOT /mnt/c/...)
```
All match → no more bridge; the variable-mangling and CRLF traps are gone.

## Optional one-click launch (Windows shortcut / Terminal profile)
```
wsl -d Ubuntu --cd ~ -- bash -lic 'cd ~/ph3b3 && claude'
```
Use a **login-interactive** shell (`bash -lic`) so nvm is sourced — otherwise `claude`
won't be on PATH in a bare `wsl -- claude`.

---

## Still applies after the move
- **never-push from Athena** — pull-only; pushes go via Nyx.
- `~/ph3b3/.gitattributes` (Phase C) is committed locally on `athena-solo` as **c84cae5** (ahead 1, NOT pushed — reaches origin via Nyx).
- Authoritative clone is native ext4 `~/ph3b3`; the OneDrive copy was retired 2026-06-23.
