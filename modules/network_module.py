import subprocess
import logging
import os
import socket
import json
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("ph3b3.network")
SCAN_DIR = Path.home() / "ph3b3_data" / "scans"
NET_LOG  = Path.home() / "ph3b3_data" / "network" / "scan_log.jsonl"

# Scan retention: the scan log (scan_log.jsonl) and raw scan files (scans/scan_*.txt)
# both record device IPs/MACs, so entries/files older than this are purged on write
# and at startup. Privacy default is 7 days; set PH3B3_SCAN_LOG_TTL_DAYS=0 to disable.
SCAN_LOG_TTL_DAYS = int(os.getenv("PH3B3_SCAN_LOG_TTL_DAYS", "7"))

NMAP_PRESETS = {
    "quick": ["-F"],
    "ports": ["-p", "1-1024"],
    "os":    ["-O"],
    "full":  ["-A"],
}

TOOLS_MENU = """\
Network tools — say the name or number to run:

  1. arp_scan            list LAN devices (IP, MAC, vendor)
  2. netdiscover         passive ARP listener (~30 s)
  3. dig <domain>        full DNS record lookup
  4. traceroute <host>   trace network path to host
  5. speedtest           internet speed test
  6. nmap quick <target> fast scan (-F)
  7. nmap ports <target> ports 1-1024
  8. nmap os <target>    OS detection (-O)
  9. nmap full <target>  aggressive scan (-A)

Example: "run arp scan" or "dig github.com" or "nmap full 192.168.0.10"\
"""


class NetworkModule:
    def __init__(self):
        SCAN_DIR.mkdir(parents=True, exist_ok=True)
        NET_LOG.parent.mkdir(parents=True, exist_ok=True)
        self._prune_log()
        self._prune_scans()
        log.info("Network module ready.")

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, tool: str, target: str, result: str) -> None:
        entry = {
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tool": tool,
            "target": target,
            "result_summary": str(result)[:300],
        }
        try:
            with NET_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            log.warning(f"Network log write failed: {e}")
        self._prune_log()

    def _prune_log(self) -> None:
        """Drop scan-log entries older than SCAN_LOG_TTL_DAYS (privacy retention).

        Rewrites scan_log.jsonl keeping only datable, in-window entries. Lines
        that aren't valid JSON or lack a parseable timestamp are dropped, since
        an undatable entry can't be proven to fall within the retention window.
        """
        if SCAN_LOG_TTL_DAYS <= 0 or not NET_LOG.exists():
            return
        cutoff = datetime.utcnow() - timedelta(days=SCAN_LOG_TTL_DAYS)
        kept = []
        try:
            for line in NET_LOG.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    ts = datetime.strptime(json.loads(line)["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    continue
                if ts >= cutoff:
                    kept.append(line)
            NET_LOG.write_text("".join(l + "\n" for l in kept), encoding="utf-8")
        except OSError as e:
            log.warning(f"Network log prune failed: {e}")

    def _prune_scans(self) -> None:
        """Delete raw scan files (scans/scan_*.txt) older than the retention window."""
        if SCAN_LOG_TTL_DAYS <= 0 or not SCAN_DIR.exists():
            return
        cutoff = (datetime.now() - timedelta(days=SCAN_LOG_TTL_DAYS)).timestamp()
        try:
            for f in SCAN_DIR.glob("scan_*.txt"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except OSError as e:
                    log.warning(f"Scan file prune failed for {f.name}: {e}")
        except OSError as e:
            log.warning(f"Scan dir prune failed: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _run(self, cmd: list, timeout: int = 60, sudo: bool = False) -> subprocess.CompletedProcess:
        if sudo:
            cmd = ["sudo", "-n"] + cmd  # -n: fail rather than prompt for password
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _default_iface(self) -> str:
        try:
            r = subprocess.run(["ip", "route", "show", "default"],
                               capture_output=True, text=True)
            parts = r.stdout.split()
            if "dev" in parts:
                return parts[parts.index("dev") + 1]
        except Exception:
            pass
        return "eth0"

    # ── Existing methods ──────────────────────────────────────────────────────

    def my_ip(self):
        try:
            import netifaces
            result = []
            for iface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(iface)
                if netifaces.AF_INET in addrs:
                    for addr in addrs[netifaces.AF_INET]:
                        ip = addr.get("addr", "")
                        if ip and not ip.startswith("127."):
                            result.append(f"{iface}: {ip}")
            return "\n".join(result) if result else "No active interfaces found."
        except Exception as e:
            return f"Error: {e}"

    def scan_network(self, target="192.168.0.0/24", quick=True):
        try:
            flags = "-sn" if quick else "-sV --open"
            cmd = ["nmap", flags, target, "-oX", "-"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            save = SCAN_DIR / f"scan_{ts}.txt"
            save.write_text(result.stdout)
            self._prune_scans()
            lines = [l for l in result.stdout.split("\n")
                     if "report" in l.lower() or "open" in l.lower()]
            summary = "\n".join(lines[:30])
            return f"Scan complete. Saved to {save.name}\n\n{summary}"
        except subprocess.TimeoutExpired:
            return "Scan timed out."
        except Exception as e:
            return f"Scan error: {e}"

    def port_scan(self, host, ports="1-1000"):
        try:
            result = subprocess.run(
                ["nmap", "-p", ports, "--open", host],
                capture_output=True, text=True, timeout=60
            )
            return result.stdout
        except Exception as e:
            return f"Port scan error: {e}"

    def who_is_on_network(self):
        try:
            result = subprocess.run(
                ["nmap", "-sn", "192.168.0.0/24", "--open"],
                capture_output=True, text=True, timeout=60
            )
            lines = [l for l in result.stdout.split("\n")
                     if "report" in l.lower() or "MAC" in l]
            return "\n".join(lines) if lines else "No hosts found."
        except Exception as e:
            return f"Error: {e}"

    def lookup_ip(self, ip):
        try:
            result = subprocess.run(["nmap", "-sV", ip],
                                    capture_output=True, text=True, timeout=30)
            return result.stdout[:1000]
        except Exception as e:
            return f"Error: {e}"

    def active_connections(self):
        try:
            result = subprocess.run(["ss", "-tupn"], capture_output=True, text=True)
            return "\n".join(result.stdout.split("\n")[:30])
        except Exception as e:
            return f"Error: {e}"

    def dns_lookup(self, host):
        try:
            ip = socket.gethostbyname(host)
            return f"{host} resolves to {ip}"
        except Exception as e:
            return f"DNS lookup failed: {e}"

    def wifi_networks(self):
        try:
            result = subprocess.run(
                ["nmcli", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
                capture_output=True, text=True
            )
            return result.stdout
        except Exception as e:
            return f"Error: {e}"

    # ── New tools ─────────────────────────────────────────────────────────────

    def arp_scan(self):
        """List all LAN devices with IP, MAC, and vendor via arp-scan or nmap fallback."""
        output = ""
        try:
            r = self._run(["arp-scan", "--localnet"], timeout=30, sudo=True)
            if r.returncode == 0 and r.stdout.strip():
                output = r.stdout
            else:
                raise RuntimeError(r.stderr or "arp-scan returned no output")
        except Exception as primary_err:
            log.info(f"arp-scan failed ({primary_err}), falling back to nmap + arp table")
            try:
                nmap_r = self._run(["nmap", "-sn", "192.168.0.0/24"], timeout=60)
                arp_r  = self._run(["arp", "-a"], timeout=10)
                output = "=== nmap host discovery ===\n" + nmap_r.stdout
                output += "\n=== ARP table ===\n" + arp_r.stdout
            except Exception as fallback_err:
                return f"ARP scan failed: primary={primary_err}, fallback={fallback_err}"

        self._log("arp_scan", "localnet", output)
        return output

    def netdiscover_passive(self, duration: int = 30):
        """Listen passively for ARP traffic to discover network devices."""
        iface = self._default_iface()
        try:
            # -P = print to stdout in parseable format; -p = passive (no probe packets)
            r = self._run(
                ["netdiscover", "-p", "-P", "-i", iface],
                timeout=duration + 5,
                sudo=True,
            )
            output = (r.stdout or r.stderr or "").strip()
            if not output:
                output = f"No ARP traffic captured on {iface} in {duration}s."
        except subprocess.TimeoutExpired:
            output = f"Passive scan completed ({duration}s) — no parseable ARP traffic on {iface}."
        except Exception as e:
            return f"netdiscover error: {e}"

        self._log("netdiscover_passive", iface, output)
        return output

    def dig_lookup(self, domain: str):
        """Full DNS lookup — A, AAAA, MX, NS, TXT records."""
        results = []
        for rtype in ("A", "AAAA", "MX", "NS", "TXT"):
            try:
                r = self._run(
                    ["dig", "+noall", "+answer", domain, rtype],
                    timeout=10,
                )
                if r.stdout.strip():
                    results.append(f"--- {rtype} ---\n{r.stdout.strip()}")
            except Exception as e:
                results.append(f"--- {rtype} --- error: {e}")

        output = "\n".join(results) if results else "No records found."
        self._log("dig_lookup", domain, output)
        return output

    def traceroute(self, host: str):
        """Trace the network path to a host using tracepath."""
        try:
            r = self._run(["tracepath", "-n", host], timeout=30)
            output = r.stdout or r.stderr or "No output."
        except subprocess.TimeoutExpired:
            output = f"tracepath to {host} timed out after 30s."
        except Exception as e:
            return f"Traceroute error: {e}"

        self._log("traceroute", host, output)
        return output

    def speedtest(self):
        """Run speedtest-cli and return ping, download, and upload results."""
        try:
            r = self._run(["speedtest-cli", "--simple"], timeout=90)
            if r.returncode != 0:
                return ("speedtest-cli not installed or failed.\n"
                        "Install: pip install speedtest-cli\n"
                        f"Error: {r.stderr.strip()}")
            output = r.stdout.strip() or "No output from speedtest-cli."
        except FileNotFoundError:
            return ("speedtest-cli not installed.\n"
                    "Install it: pip install speedtest-cli  (or rerun setup.sh)")
        except subprocess.TimeoutExpired:
            return "Speedtest timed out after 90s."
        except Exception as e:
            return f"Speedtest error: {e}"

        self._log("speedtest", "internet", output)
        return output

    def nmap_expand(self, target: str, flags: str = None):
        """Flexible nmap scan with preset flag profiles.

        flags: "quick" (-F), "ports" (-p 1-1024), "os" (-O), "full" (-A).
        Defaults to -sV if no preset is given.
        """
        flag_args = NMAP_PRESETS.get(flags, ["-sV"])
        needs_root = flags == "os"  # -O requires raw socket privileges
        try:
            r = self._run(["nmap"] + flag_args + [target],
                          timeout=180, sudo=needs_root)
            output = r.stdout or r.stderr or "No output."
        except subprocess.TimeoutExpired:
            return f"nmap timed out scanning {target}."
        except Exception as e:
            return f"nmap error: {e}"

        self._log(f"nmap_expand:{flags or 'default'}", target, output)
        return output

    def tools_menu(self):
        """Return the interactive network tools menu."""
        return TOOLS_MENU
