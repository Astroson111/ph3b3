import subprocess
import logging
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ph3b3.system")

class SystemModule:
    def __init__(self):
        self._has_nvidia = self._check_nvidia()
        self._has_psutil = self._check_psutil()
        log.info(f"System module ready. GPU: {self._has_nvidia} psutil: {self._has_psutil}")

    def _check_nvidia(self):
        try:
            result = subprocess.run(["which", "nvidia-smi"], capture_output=True)
            return result.returncode == 0
        except Exception:
            return False

    def _check_psutil(self):
        try:
            import psutil
            return True
        except ImportError:
            return False

    def _run(self, cmd, timeout=10):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.stdout.strip()
        except Exception as e:
            return f"Error: {e}"

    def gpu_status(self):
        if not self._has_nvidia:
            return "nvidia-smi not available."
        return self._run([
            "nvidia-smi",
            "--query-gpu=name,temperature.gpu,utilization.gpu,utilization.memory,memory.used,memory.total",
            "--format=csv,noheader,nounits"
        ])

    def cpu_status(self):
        if self._has_psutil:
            import psutil
            cpu = psutil.cpu_percent(interval=1)
            freq = psutil.cpu_freq()
            cores = psutil.cpu_count()
            return f"CPU: {cpu}% | Cores: {cores} | Freq: {freq.current:.0f}MHz"
        result = self._run(["grep", "-m1", "cpu MHz", "/proc/cpuinfo"])
        load = self._run(["cat", "/proc/loadavg"])
        return f"{result}\nLoad: {load}"

    def ram_status(self):
        if self._has_psutil:
            import psutil
            mem = psutil.virtual_memory()
            used = mem.used // (1024**2)
            total = mem.total // (1024**2)
            pct = mem.percent
            return f"RAM: {used}MB / {total}MB ({pct}% used)"
        return self._run(["free", "-h"])

    def disk_status(self):
        return self._run(["df", "-h", "/home"])

    def temps(self):
        try:
            result = subprocess.run(["sensors"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return result.stdout.strip()
            return "sensors not available. Run: sudo apt install lm-sensors"
        except Exception:
            return "Temperature data unavailable."

    def uptime(self):
        return self._run(["uptime", "-p"])

    def ollama_status(self):
        result = self._run(["systemctl", "is-active", "ollama"])
        if "active" in result:
            models = self._run(["ollama", "list"])
            return f"Ollama: running\n{models}"
        return "Ollama: not running. Run: sudo systemctl start ollama"

    def full_status(self):
        sections = [
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]",
            f"Uptime: {self.uptime()}",
            f"CPU: {self.cpu_status()}",
            f"RAM: {self.ram_status()}",
            f"Disk: {self.disk_status()}",
            f"GPU: {self.gpu_status()}",
            f"Ollama: {self.ollama_status()}",
        ]
        return "\n".join(sections)
