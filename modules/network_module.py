import subprocess
import logging
import socket
import json
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ph3b3.network")
SCAN_DIR = Path.home() / "ph3b3_data" / "scans"

class NetworkModule:
    def __init__(self):
        SCAN_DIR.mkdir(parents=True, exist_ok=True)
        log.info("Network module ready.")

    def my_ip(self):
        try:
            import netifaces
            result = []
            for iface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(iface)
                if netifaces.AF_INET in addrs:
                    for addr in addrs[netifaces.AF_INET]:
                        ip = addr.get("addr","")
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
            lines = [l for l in result.stdout.split("\n") if "report" in l.lower() or "open" in l.lower()]
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
            lines = [l for l in result.stdout.split("\n") if "report" in l.lower() or "MAC" in l]
            return "\n".join(lines) if lines else "No hosts found."
        except Exception as e:
            return f"Error: {e}"

    def lookup_ip(self, ip):
        try:
            result = subprocess.run(["nmap", "-sV", ip], capture_output=True, text=True, timeout=30)
            return result.stdout[:1000]
        except Exception as e:
            return f"Error: {e}"

    def active_connections(self):
        try:
            result = subprocess.run(["ss", "-tupn"], capture_output=True, text=True)
            lines = result.stdout.split("\n")[:30]
            return "\n".join(lines)
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
