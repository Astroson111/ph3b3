import subprocess
import logging
import requests
import hashlib
from datetime import datetime

log = logging.getLogger("ph3b3.cybersec")

class CybersecModule:
    def __init__(self):
        log.info("Cybersec module ready.")

    def cve_lookup(self, cve_id):
        try:
            url = f"https://cve.circl.lu/api/cve/{cve_id.upper()}"
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                return f"CVE not found: {cve_id}"
            data = r.json()
            summary = data.get("summary", "No summary.")
            cvss = data.get("cvss", "N/A")
            published = data.get("Published", "N/A")[:10]
            refs = data.get("references", [])[:3]
            ref_lines = "\n".join(refs)
            return (
                f"{cve_id.upper()}\n"
                f"CVSS: {cvss}\n"
                f"Published: {published}\n\n"
                f"Summary: {summary}\n\n"
                f"References:\n{ref_lines}"
            )
        except Exception as e:
            return f"CVE lookup error: {e}"

    def hash_file(self, filepath):
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            md5 = hashlib.md5(data).hexdigest()
            sha1 = hashlib.sha1(data).hexdigest()
            sha256 = hashlib.sha256(data).hexdigest()
            return f"MD5:    {md5}\nSHA1:   {sha1}\nSHA256: {sha256}"
        except Exception as e:
            return f"Hash error: {e}"

    def hash_string(self, text):
        data = text.encode()
        return (
            f"MD5:    {hashlib.md5(data).hexdigest()}\n"
            f"SHA1:   {hashlib.sha1(data).hexdigest()}\n"
            f"SHA256: {hashlib.sha256(data).hexdigest()}"
        )

    def check_hash_haveibeenpwned(self, password):
        try:
            sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
            prefix = sha1[:5]
            suffix = sha1[5:]
            r = requests.get(
                f"https://api.pwnedpasswords.com/range/{prefix}",
                timeout=10
            )
            if r.status_code == 200:
                for line in r.text.splitlines():
                    h, count = line.split(":")
                    if h == suffix:
                        return f"Password found {count} times in breach data. Do not use."
                return "Password not found in known breaches."
            return "Could not reach HaveIBeenPwned API."
        except Exception as e:
            return f"HIBP error: {e}"

    def whois(self, domain):
        try:
            result = subprocess.run(
                ["whois", domain],
                capture_output=True, text=True, timeout=15
            )
            lines = [l for l in result.stdout.split("\n")
                     if any(k in l.lower() for k in
                     ["registrar", "creation", "expiry", "updated", "name server", "status"])]
            return "\n".join(lines[:15]) if lines else result.stdout[:500]
        except Exception as e:
            return f"Whois error: {e}"

    def open_ports(self, host):
        try:
            result = subprocess.run(
                ["nmap", "-F", "--open", host],
                capture_output=True, text=True, timeout=30
            )
            return result.stdout
        except Exception as e:
            return f"Port scan error: {e}"

    def header_check(self, url):
        try:
            r = requests.head(url, timeout=10, allow_redirects=True)
            headers = dict(r.headers)
            security_headers = [
                "Strict-Transport-Security",
                "Content-Security-Policy",
                "X-Frame-Options",
                "X-Content-Type-Options",
                "Referrer-Policy",
                "Permissions-Policy",
            ]
            lines = [f"Status: {r.status_code}"]
            for h in security_headers:
                val = headers.get(h, "MISSING")
                lines.append(f"{h}: {val}")
            return "\n".join(lines)
        except Exception as e:
            return f"Header check error: {e}"

    def encode_decode(self, text, mode="b64encode"):
        import base64
        try:
            if mode == "b64encode":
                return base64.b64encode(text.encode()).decode()
            elif mode == "b64decode":
                return base64.b64decode(text).decode()
            elif mode == "hex":
                return text.encode().hex()
            elif mode == "unhex":
                return bytes.fromhex(text).decode()
            return f"Unknown mode: {mode}"
        except Exception as e:
            return f"Encode/decode error: {e}"

    def subnet_info(self, cidr):
        try:
            import ipaddress
            net = ipaddress.ip_network(cidr, strict=False)
            return (
                f"Network:   {net.network_address}\n"
                f"Broadcast: {net.broadcast_address}\n"
                f"Netmask:   {net.netmask}\n"
                f"Hosts:     {net.num_addresses - 2}\n"
                f"Range:     {list(net.hosts())[0]} - {list(net.hosts())[-1]}"
            )
        except Exception as e:
            return f"Subnet error: {e}"

    def traceroute(self, host):
        try:
            result = subprocess.run(
                ["traceroute", "-m", "15", host],
                capture_output=True, text=True, timeout=30
            )
            return result.stdout
        except Exception as e:
            return f"Traceroute error: {e}"

    def ssl_check(self, host, port=443):
        try:
            result = subprocess.run(
                ["openssl", "s_client", "-connect", f"{host}:{port}",
                 "-servername", host],
                input="Q",
                capture_output=True, text=True, timeout=10
            )
            lines = [l for l in result.stdout.split("\n")
                     if any(k in l for k in
                     ["subject", "issuer", "Not Before", "Not After", "Verify"])]
            return "\n".join(lines) if lines else "Could not retrieve SSL info."
        except Exception as e:
            return f"SSL check error: {e}"

    def dns_records(self, domain):
        try:
            types = ["A", "MX", "TXT", "NS", "CNAME"]
            results = []
            for record_type in types:
                result = subprocess.run(
                    ["dig", "+short", record_type, domain],
                    capture_output=True, text=True, timeout=10
                )
                if result.stdout.strip():
                    results.append(f"{record_type}: {result.stdout.strip()}")
            return "\n".join(results) if results else "No DNS records found."
        except Exception as e:
            return f"DNS error: {e}"

    def http_methods(self, url):
        try:
            result = subprocess.run(
                ["curl", "-s", "-X", "OPTIONS", "-i", url],
                capture_output=True, text=True, timeout=10
            )
            lines = [l for l in result.stdout.split("\n")
                     if "Allow" in l or "HTTP" in l]
            return "\n".join(lines) if lines else "No methods returned."
        except Exception as e:
            return f"Error: {e}"

    def robots_txt(self, domain):
        try:
            url = f"https://{domain}/robots.txt"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return r.text[:1000]
            return f"No robots.txt found at {url}"
        except Exception as e:
            return f"Error: {e}"

    def ping(self, host, count=4):
        try:
            result = subprocess.run(
                ["ping", "-c", str(count), host],
                capture_output=True, text=True, timeout=15
            )
            return result.stdout
        except Exception as e:
            return f"Ping error: {e}"

    def local_services(self):
        try:
            result = subprocess.run(
                ["ss", "-tulpn"],
                capture_output=True, text=True
            )
            lines = result.stdout.split("\n")
            listening = [l for l in lines if "LISTEN" in l]
            return "\n".join(listening) if listening else "No listening services found."
        except Exception as e:
            return f"Error: {e}"

    def arp_table(self):
        try:
            result = subprocess.run(
                ["arp", "-n"],
                capture_output=True, text=True
            )
            return result.stdout
        except Exception as e:
            return f"ARP error: {e}"

    def mac_lookup(self, mac):
        try:
            prefix = mac.replace(":", "").replace("-", "")[:6].upper()
            r = requests.get(
                f"https://api.macvendors.com/{prefix}",
                timeout=10
            )
            if r.status_code == 200:
                return f"{mac} — {r.text.strip()}"
            return f"Vendor not found for {mac}"
        except Exception as e:
            return f"MAC lookup error: {e}"

    def study_topic(self, topic):
        topics = {
            "sql injection": "SQLi: attacker inserts malicious SQL into input fields. Types: classic, blind, time-based. Prevention: parameterized queries, prepared statements, input validation. Tools: sqlmap.",
            "xss": "Cross-Site Scripting: injecting malicious scripts into web pages. Types: reflected, stored, DOM-based. Prevention: output encoding, CSP headers, input sanitization.",
            "buffer overflow": "Writing data beyond buffer boundaries to overwrite adjacent memory. Stack vs heap overflow. Exploitation: control EIP/RIP, shellcode injection. Mitigations: ASLR, DEP, stack canaries.",
            "privilege escalation": "Moving from lower to higher privileges. Linux: SUID binaries, sudo misconfig, cron jobs, kernel exploits. Windows: token impersonation, unquoted paths, registry keys.",
            "reconnaissance": "Information gathering phase. Passive: OSINT, Shodan, Google dorks. Active: nmap, banner grabbing, DNS enumeration. Goal: map attack surface before exploitation.",
            "metasploit": "Framework for developing and executing exploits. Modules: auxiliary, exploit, payload, post. msfconsole -> search -> use -> set options -> run. Meterpreter is the gold standard payload.",
            "burp suite": "Web app testing proxy. Intercept and modify HTTP requests. Key tools: Repeater, Intruder, Scanner, Decoder. Essential for manual web app pentesting.",
            "owasp top 10": "The ten most critical web application security risks. Injection, Broken Auth, Sensitive Data Exposure, XXE, Broken Access Control, Security Misconfiguration, XSS, Insecure Deserialization, Vulnerable Components, Insufficient Logging.",
            "nmap": "Network scanner. -sn: ping sweep. -sV: version detection. -O: OS detection. -p: port range. -A: aggressive. -oX: XML output. --script: NSE scripts.",
            "wireshark": "Packet analyzer. Capture and inspect network traffic. Filters: ip.addr==, tcp.port==, http, dns. Follow TCP stream to reconstruct sessions. Export objects to extract files.",
            "cryptography": "Symmetric: AES, DES, same key for encrypt/decrypt. Asymmetric: RSA, elliptic curve, public/private keypair. Hashing: MD5 broken, SHA1 deprecated, SHA256 current standard. PKI: certificates, CAs, chain of trust.",
            "social engineering": "Manipulating humans rather than systems. Phishing, spear phishing, vishing, pretexting, baiting. The weakest link is always the human. Mitigations: training, policies, verification procedures.",
        }
        q = topic.lower().strip()
        for key, val in topics.items():
            if q in key or key in q:
                return f"[{key.upper()}]\n{val}"
        return f"No study note for '{topic}'. Try: sql injection, xss, buffer overflow, privilege escalation, reconnaissance, metasploit, burp suite, owasp top 10, nmap, wireshark, cryptography, social engineering."
