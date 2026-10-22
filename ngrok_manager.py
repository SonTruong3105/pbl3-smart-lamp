"""Ngrok process manager.

- Check xem ngrok da chay chua (qua web UI API 4040)
- Neu chua -> spawn ngrok subprocess
- Tra ve URL co dinh
"""
import os
import sys
import time
import json
import subprocess
import threading
from typing import Optional
from pathlib import Path


def _log(msg: str):
    print(f"[NGROK] {msg}", file=sys.stderr, flush=True)


def _find_ngrok() -> str:
    """Tim ngrok.exe: uu tien cung thu muc, roi den PATH."""
    local_exe = Path(__file__).parent / "ngrok.exe"
    if local_exe.exists():
        return str(local_exe)
    local_no_ext = Path(__file__).parent / "ngrok"
    if local_no_ext.exists():
        return str(local_no_ext)
    return "ngrok"


def _is_ngrok_running() -> bool:
    """Kiem tra ngrok co dang chay khong qua web UI API 4040."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:4040/api/tunnels",
            headers={"User-Agent": "xiaozhi-checker"},
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.loads(r.read())
            tunnels = data.get("tunnels", [])
            return len(tunnels) > 0
    except Exception:
        return False


class NgrokProcess:
    """Quan ly ngrok nhu subprocess."""

    def __init__(self, domain: str, port: int = 8000, ngrok_path: str = "ngrok"):
        self.domain = domain
        self.port = port
        self.ngrok_path = ngrok_path
        self.process: Optional[subprocess.Popen] = None
        self.url = f"https://{domain}"
        self._already_running = False

    def start(self, timeout: int = 20) -> str:
        """Start ngrok neu chua chay. Tra ve URL."""
        # Check neu da co ngrok chay
        if _is_ngrok_running():
            _log("Ngrok da chay san -> dung instance hien tai")
            self._already_running = True
            return self.url

        # Build command
        cmd = [
            self.ngrok_path,
            "http",
            f"--url=https://{self.domain}",
            str(self.port),
            "--log=stdout",
        ]
        _log(f"Start: {' '.join(cmd)}")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"Khong tim thay ngrok tai: {self.ngrok_path}\n"
                "Tai tai: https://ngrok.com/download"
            )

        # Thread doc output de tranh block pipe
        def _reader():
            try:
                for line in iter(self.process.stdout.readline, ""):
                    line = line.strip()
                    if line:
                        _log(f"[ngrok] {line}")
            except Exception:
                pass

        threading.Thread(target=_reader, daemon=True).start()

        # Doi ngrok ready
        start_t = time.time()
        while time.time() - start_t < timeout:
            if _is_ngrok_running():
                _log(f"Ngrok ready: {self.url}")
                return self.url
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"Ngrok exited with code {self.process.returncode}. "
                    "Check log phia tren."
                )
            time.sleep(0.5)

        raise TimeoutError(f"Ngrok khong ready sau {timeout}s")

    def stop(self):
        """Stop ngrok neu no do minh start (khong kill ngrok cua nguoi khac)."""
        if self._already_running:
            _log("Ngrok do user start -> khong kill")
            return
        if self.process:
            _log("Stop ngrok...")
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None


# Singleton
_instance: Optional[NgrokProcess] = None


def start_ngrok(domain: str, port: int = 8000) -> NgrokProcess:
    """Start ngrok singleton."""
    global _instance
    if _instance is None:
        _instance = NgrokProcess(domain=domain, port=port)
        _instance.ngrok_path = _find_ngrok()
    _instance.start()
    return _instance