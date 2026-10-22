"""Cloudflare Quick Tunnel Manager.
Tu dong start cloudflared, lay URL trycloudflare.com.
"""
import subprocess
import re
import time
import threading
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class CloudflareQuickTunnel:
    """Quan ly Cloudflare Quick Tunnel nhu subprocess."""

    URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

    def __init__(self, port: int = 8000, cloudflared_path: str = "cloudflared"):
        self.port = port
        self.cloudflared_path = cloudflared_path
        self.process: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None

    def start(self, timeout: int = 30) -> str:
        """Start cloudflared, tra ve URL."""
        if self.process and self.process.poll() is None:
            logger.warning("Tunnel da chay, tra URL hien tai.")
            return self.public_url

        cmd = [
            self.cloudflared_path,
            "tunnel",
            "--url", f"http://127.0.0.1:{self.port}",
            "--no-autoupdate",
        ]
        logger.info(f"Start: {' '.join(cmd)}")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"Khong tim thay cloudflared tai: {self.cloudflared_path}\n"
                "Tai tai: https://developers.cloudflare.com/cloudflare-one/"
                "connections/connect-networks/downloads/"
            )

        self._stop_event.clear()
        url_found = threading.Event()

        def _read_output():
            try:
                for line in iter(self.process.stdout.readline, ""):
                    if self._stop_event.is_set():
                        break
                    line = line.strip()
                    if line:
                        logger.debug(f"[cloudflared] {line}")
                    if not url_found.is_set():
                        match = self.URL_PATTERN.search(line)
                        if match:
                            self.public_url = match.group(0)
                            logger.info(f"Cloudflare URL: {self.public_url}")
                            url_found.set()
            except Exception as e:
                logger.error(f"Read output error: {e}")

        self._reader_thread = threading.Thread(target=_read_output, daemon=True)
        self._reader_thread.start()

        if not url_found.wait(timeout):
            self.stop()
            raise TimeoutError(f"Khong lay duoc URL sau {timeout}s")

        return self.public_url

    def stop(self):
        """Stop cloudflared."""
        logger.info("Stop Cloudflare Tunnel...")
        self._stop_event.set()

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception:
                pass
            self.process = None

        if self._reader_thread:
            self._reader_thread.join(timeout=2)
            self._reader_thread = None

        self.public_url = None
        logger.info("Cloudflare Tunnel stopped.")


# Singleton
_tunnel_instance: Optional[CloudflareQuickTunnel] = None


def get_tunnel(port: int = 8000) -> CloudflareQuickTunnel:
    """Lay singleton tunnel."""
    global _tunnel_instance
    if _tunnel_instance is None:
        _tunnel_instance = CloudflareQuickTunnel(port=port)
    return _tunnel_instance