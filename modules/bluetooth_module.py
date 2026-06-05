import subprocess
import logging
import re
from datetime import datetime

log = logging.getLogger("ph3b3.bluetooth")

KNOWN_DEVICES = {
    # Add your devices here as you pair them
    # "AA:BB:CC:DD:EE:FF": "Owner Device",
}

class BluetoothModule:
    def __init__(self):
        self._available = self._check()
        if self._available:
            log.info("Bluetooth module ready.")
        else:
            log.warning("bluetoothctl not found.")

    def _check(self):
        try:
            result = subprocess.run(["which", "bluetoothctl"], capture_output=True)
            return result.returncode == 0
        except Exception:
            return False

    def _run(self, cmd, timeout=10):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            return "Bluetooth command timed out."
        except Exception as e:
            return f"Bluetooth error: {e}"

    def scan(self, seconds=10):
        if not self._available:
            return "bluetoothctl not available."
        try:
            result = subprocess.run(
                ["timeout", str(seconds), "bluetoothctl", "scan", "on"],
                capture_output=True, text=True
            )
            devices = re.findall(r"Device ([0-9A-F:]{17}) (.+)", result.stdout)
            if not devices:
                return "No devices found during scan."
            lines = []
            for mac, name in devices:
                known = KNOWN_DEVICES.get(mac, "unknown")
                lines.append(f"{mac} — {name.strip()} [{known}]")
            return "\n".join(lines)
        except Exception as e:
            return f"Scan error: {e}"

    def paired_devices(self):
        if not self._available:
            return "bluetoothctl not available."
        output = self._run(["bluetoothctl", "paired-devices"])
        if not output:
            return "No paired devices."
        lines = []
        for line in output.split("\n"):
            match = re.search(r"Device ([0-9A-F:]{17}) (.+)", line)
            if match:
                mac = match.group(1)
                name = match.group(2).strip()
                known = KNOWN_DEVICES.get(mac, name)
                lines.append(f"{mac} — {known}")
        return "\n".join(lines) if lines else "No paired devices found."

    def is_device_nearby(self, mac):
        try:
            result = subprocess.run(
                ["hcitool", "cc", mac],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def check_known_devices(self):
        if not KNOWN_DEVICES:
            return "No known devices configured."
        nearby = []
        for mac, name in KNOWN_DEVICES.items():
            if self.is_device_nearby(mac):
                nearby.append(f"{name} ({mac}) is nearby.")
        if nearby:
            return "\n".join(nearby)
        return "No known devices in range."

    def controller_info(self):
        return self._run(["bluetoothctl", "show"])

    def register_device(self, mac, name):
        KNOWN_DEVICES[mac] = name
        return f"Registered: {name} ({mac})"

    def status(self):
        if not self._available:
            return "Bluetooth not available."
        output = self._run(["bluetoothctl", "show"])
        powered = "yes" in output.lower()
        return f"Bluetooth {'powered and ready' if powered else 'present but not powered'}."
