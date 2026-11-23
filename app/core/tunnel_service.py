"""TunnelService — Cloudflare Tunnel (Windows + Ubuntu, any event loop).

Fix v2:
- Kill TẤT CẢ cloudflared cũ trước khi spawn mới (tránh tích lũy connector rác)
- Skip kill-all nếu Windows có cloudflared service đang chạy
- Clear PUBLIC_WS_URL khi spawn fail (OTA fallback về LAN Host header)
- Support `tunnel.protocol: http2` nếu ISP chặn QUIC
- Tăng startup wait 2s → 3s để cloudflared kịp register
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from loguru import logger

from app.config import config


ROOT = Path(__file__).parent.parent.parent.resolve()
_QUICK_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def _creationflags() -> int:
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def _find_cloudflared(explicit: str = "") -> Optional[str]:
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return str(p)
        logger.warning(f"cloudflared_path='{explicit}' không tồn tại")
    for name in ("cloudflared.exe", "cloudflared"):
        local = ROOT / name
        if local.exists():
            return str(local)
    return shutil.which("cloudflared")


def _find_config(explicit: str = "") -> Optional[Path]:
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return p
        logger.warning(f"config_path='{explicit}' không tồn tại")
        return None
    default = Path.home() / ".cloudflared" / "config.yml"
    return default if default.exists() else None


class TunnelService:
    """Quản lý Cloudflare Tunnel qua subprocess.Popen (cross-platform, cross-loop)."""

    def __init__(self):
        self.enabled = config.tunnel_enabled
        self.mode = config.tunnel_mode
        self.domain = config.tunnel_domain
        self.port = config.tunnel_port
        self._cfg_path_override = config.tunnel_config_path
        self._cf_path_override = config.tunnel_cloudflared_path
        self.auto_restart = config.tunnel_auto_restart
        self.restart_delay = config.tunnel_restart_delay
        self.max_restart = config.tunnel_max_restart
        # ⭐ NEW: đọc protocol từ config (quic mặc định, http2 nếu ISP chặn UDP)
        self.protocol = (
            config._get("tunnel", "protocol", default="quic") or "quic"
        ).lower()

        self._process: Optional[subprocess.Popen] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._supervisor_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._public_url: str = ""
        self._restart_count = 0
        self._cf_path: str = ""
        self._cfg_path: Optional[Path] = None
        self._last_exit_reason = ""
        # Track xem connector đã register ít nhất 1 lần chưa
        self._has_registered = False

    async def start(self) -> bool:
        if not self.enabled:
            logger.info("🌐 Tunnel disabled")
            return False

        # ⭐ FIX QUAN TRỌNG: Kill TẤT CẢ cloudflared cũ trước khi spawn mới
        # Tránh tích lũy hàng chục process → Cloudflare Edge reject connector mới
        await self._kill_all_cloudflared()

        if self.is_running():
            logger.info("🌐 Tunnel đã chạy")
            return True
        if self.mode not in ("named", "quick"):
            logger.error(f"❌ tunnel.mode='{self.mode}' không hợp lệ")
            return False
        if not self._validate():
            return False
        if not await self._spawn():
            # ⭐ FIX: Clear PUBLIC_WS_URL để OTA fallback về Host header (LAN IP)
            os.environ.pop("PUBLIC_WS_URL", None)
            self._public_url = ""
            logger.warning(
                "🌐 Tunnel fail — đã xóa PUBLIC_WS_URL. "
                "OTA sẽ fallback về Host header (LAN IP)."
            )
            return False
        if self.auto_restart:
            self._supervisor_task = asyncio.create_task(self._supervisor())
        return True

    async def stop(self):
        self._stop_event.set()
        if self._supervisor_task:
            self._supervisor_task.cancel()
            try:
                await self._supervisor_task
            except (asyncio.CancelledError, Exception):
                pass
            self._supervisor_task = None
        await self._kill_process()
        # ⭐ FIX: Dọn sạch cloudflared khi shutdown
        await self._kill_all_cloudflared()
        logger.info("🌐 Tunnel đã dừng")

    def get_public_url(self) -> str:
        return self._public_url

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _validate(self) -> bool:
        self._cf_path = _find_cloudflared(self._cf_path_override) or ""
        if not self._cf_path:
            logger.error("❌ Không tìm thấy cloudflared trong PATH")
            return False
        logger.info(f"🌐 cloudflared: {self._cf_path}")
        if self.mode == "named":
            if not self.domain:
                logger.error("❌ tunnel.domain trống")
                return False
            self._cfg_path = _find_config(self._cfg_path_override)
            if not self._cfg_path:
                logger.error("❌ Không tìm thấy ~/.cloudflared/config.yml")
                return False
            logger.info(f"🌐 config.yml: {self._cfg_path}")
            self._set_public_url(f"https://{self.domain}")
        return True

    def _build_cmd(self) -> list:
        # ⭐ NEW: Support protocol=http2 (tránh lỗi 0x0 nếu ISP chặn QUIC)
        common = [self._cf_path, "tunnel", "--no-autoupdate"]
        if self.protocol == "http2":
            common += ["--protocol", "http2", "--edge-ip-version", "4"]
        if self.mode == "named":
            return common + ["--config", str(self._cfg_path), "run"]
        return common + ["--url", f"http://localhost:{self.port}"]

    async def _kill_all_cloudflared(self):
        """Kill TẤT CẢ process cloudflared còn sót từ session cũ.

        ⭐ FIX: Cloudflare Edge giới hạn số connector mỗi tunnel.
        25 process cũ → Edge reject phần lớn → "Application error 0x0 (remote)".

        ⚠️ Skip nếu Windows có service `cloudflared` đang chạy — service
        tự quản lý process, kill sẽ làm service chết.
        """
        # Skip nếu có cloudflared service đang RUNNING
        if sys.platform == "win32":
            try:
                check = await asyncio.to_thread(
                    subprocess.run,
                    ["sc.exe", "query", "cloudflared"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=_creationflags(),
                )
                if check.returncode == 0 and "RUNNING" in (check.stdout or ""):
                    logger.info(
                        "🌐 cloudflared service đang RUNNING — skip kill-all "
                        "(service tự quản lý)"
                    )
                    return
            except Exception:
                pass  # Không có sc.exe hoặc lỗi — tiếp tục kill-all

        try:
            if sys.platform == "win32":
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/F", "/IM", "cloudflared.exe"],
                    capture_output=True,
                    text=True,
                    creationflags=_creationflags(),
                    timeout=10,
                )
                if result.returncode == 0:
                    logger.info("🧹 Đã dọn sạch cloudflared cũ (Windows)")
            else:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["pkill", "-9", "-f", "cloudflared"],
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    logger.info("🧹 Đã dọn sạch cloudflared cũ (Unix)")
            # Đợi 500ms để OS giải phóng port/handle trước khi spawn
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(f"Cleanup cloudflared: {e}")

    async def _spawn(self) -> bool:
        cmd = self._build_cmd()
        logger.info(f"🌐 Start tunnel [{self.mode}]: {' '.join(cmd)}")
        try:
            proc = await asyncio.to_thread(
                subprocess.Popen,
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=_creationflags(),
                bufsize=0,
            )
        except FileNotFoundError:
            logger.error(f"❌ Không chạy được cloudflared tại '{self._cf_path}'")
            return False
        except Exception as e:
            logger.exception(f"❌ Spawn tunnel lỗi: {e}")
            return False

        self._process = proc
        self._has_registered = False
        self._start_monitor_thread()

        if self.mode == "named":
            # ⭐ Tăng 2s → 3s: cloudflared cần thời gian register QUIC connection
            await asyncio.sleep(3.0)
            if proc.poll() is not None:
                logger.error(f"❌ cloudflared exited code={proc.returncode}")
                return False
            logger.success(f"🌐 Tunnel named sẵn sàng → {self._public_url}")
            return True

        # Quick: đợi URL (~20s)
        for _ in range(66):
            if self._public_url:
                logger.success(f"🌐 Tunnel quick sẵn sàng → {self._public_url}")
                return True
            if proc.poll() is not None:
                logger.error(f"❌ cloudflared exited code={proc.returncode}")
                return False
            await asyncio.sleep(0.3)

        logger.error("❌ Timeout 20s chờ URL")
        await self._kill_process()
        return False

    def _start_monitor_thread(self):
        proc = self._process
        if not proc or not proc.stdout:
            return

        def reader():
            try:
                while True:
                    raw = proc.stdout.readline()
                    if not raw:
                        break
                    text = raw.decode("utf-8", errors="replace").rstrip()
                    if not text:
                        continue
                    logger.debug(f"[cloudflared] {text}")
                    low = text.lower()
                    # ⭐ Detect connector register thành công
                    if "registered tunnel connection" in low:
                        self._has_registered = True
                        self._last_exit_reason = ""
                    # ⭐ Detect các reason thất bại cụ thể
                    if "unknown error registering the connection" in low:
                        self._last_exit_reason = "Cloudflare từ chối đăng ký connection"
                    if "application error 0x0" in low:
                        self._last_exit_reason = (
                            "Edge reject (0x0 remote) — có thể xung đột connector"
                        )
                    if "unauthorized" in low:
                        self._last_exit_reason = "Credential không hợp lệ hoặc bị thu hồi"
                    if any(k in low for k in (
                        "registered tunnel connection",
                        "connection registered",
                        "error", "failed", "unauthorized",
                    )):
                        logger.info(f"[cloudflared] {text}")
                    if self.mode == "quick" and not self._public_url:
                        m = _QUICK_URL_RE.search(text)
                        if m:
                            self._set_public_url(m.group(0))
            except Exception as e:
                logger.warning(f"⚠️ Monitor: {e}")

        self._monitor_thread = threading.Thread(
            target=reader, daemon=True, name="cf-monitor"
        )
        self._monitor_thread.start()

    async def _kill_process(self):
        proc = self._process
        self._process = None
        if not proc or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(proc.wait, timeout=8),
                    timeout=10.0,
                )
            except (asyncio.TimeoutError, subprocess.TimeoutExpired):
                logger.warning("⚠️ Force kill cloudflared")
                try:
                    proc.kill()
                    await asyncio.to_thread(proc.wait, timeout=3)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"⚠️ Stop tunnel: {e}")

    def _set_public_url(self, url: str):
        if not url or url == self._public_url:
            return
        self._public_url = url
        os.environ["PUBLIC_WS_URL"] = url
        logger.info(f"🌐 PUBLIC_WS_URL = {url}")

    async def _supervisor(self):
        logger.info("🌐 Tunnel supervisor started")
        while not self._stop_event.is_set():
            try:
                if not self.is_running():
                    if self._stop_event.is_set():
                        break
                    if (
                        self.mode == "named"
                        and self._last_exit_reason
                        == "Cloudflare từ chối đăng ký connection"
                    ):
                        logger.error(
                            "❌ Named tunnel bị Cloudflare từ chối đăng ký; "
                            "dừng retry để không tạo connector rác. "
                            "Kiểm tra credential/quyền tunnel."
                        )
                        os.environ.pop("PUBLIC_WS_URL", None)
                        self._public_url = ""
                        break
                    if self._restart_count >= self.max_restart:
                        logger.error(f"❌ Crash {self._restart_count} lần — stop")
                        os.environ.pop("PUBLIC_WS_URL", None)
                        self._public_url = ""
                        break
                    delay = self.restart_delay * (1 + self._restart_count * 0.5)
                    reason = (
                        f" ({self._last_exit_reason})"
                        if self._last_exit_reason else ""
                    )
                    logger.warning(
                        f"⚠️ Tunnel process exited{reason}; "
                        f"retry #{self._restart_count + 1} sau {delay:.0f}s"
                    )
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(), timeout=delay
                        )
                        break
                    except asyncio.TimeoutError:
                        pass
                    self._restart_count += 1
                    # ⭐ FIX: Kill sạch cloudflared cũ trước khi respawn
                    await self._kill_all_cloudflared()
                    if await self._spawn():
                        logger.success("🌐 Tunnel restart OK")
                        self._last_exit_reason = ""
                await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(f"❌ Supervisor: {e}")
                await asyncio.sleep(5.0)
        logger.info("🌐 Tunnel supervisor stopped")