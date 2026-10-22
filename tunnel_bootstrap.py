"""Auto-start Ngrok + Cloudflare Quick Tunnel khi import."""
import os
import sys
import atexit
from pathlib import Path


def _log(msg: str):
    print(f"[BOOTSTRAP] {msg}", file=sys.stderr, flush=True)


# ─────────────────────────────────────────────────────────────
#  NGROK CONFIG
# ─────────────────────────────────────────────────────────────
NGROK_DOMAIN = "drone-debrief-reviver.ngrok-free.dev"
SERVER_PORT = int(os.environ.get("TUNNEL_PORT", "8000"))


def _setup_ngrok():
    """Start ngrok neu chua chay."""
    _log("=" * 50)
    _log("Checking Ngrok...")

    if os.environ.get("SKIP_NGROK") == "1":
        _log("SKIP_NGROK=1 -> bo qua ngrok")
        return

    try:
        from ngrok_manager import start_ngrok
    except ImportError as e:
        _log(f"Khong import duoc ngrok_manager: {e}")
        return

    try:
        proc = start_ngrok(domain=NGROK_DOMAIN, port=SERVER_PORT)
        _log(f"*** NGROK URL = {proc.url} ***")

        def _cleanup_ngrok():
            try:
                proc.stop()
            except Exception:
                pass

        atexit.register(_cleanup_ngrok)
    except Exception as e:
        _log(f"*** NGROK FAIL: {type(e).__name__}: {e} ***")
        _log("Server se chay ma khong co ngrok.")


def _setup_cloudflare():
    """Start Cloudflare Quick Tunnel (nhu cu)."""
    _log("=" * 50)
    _log("Checking Cloudflare Tunnel...")

    if os.environ.get("SKIP_TUNNEL") == "1":
        _log("SKIP_TUNNEL=1 -> bo qua tunnel")
        return

    try:
        from tunnel_manager import get_tunnel
    except ImportError as e:
        _log(f"Khong import duoc tunnel_manager: {e}")
        return

    cloudflared = _find_cloudflared()
    _log(f"Cloudflared path: {cloudflared}")

    tunnel = get_tunnel(port=SERVER_PORT)
    tunnel.cloudflared_path = cloudflared

    try:
        url = tunnel.start(timeout=30)
        os.environ["PUBLIC_WS_URL"] = url
        _log("=" * 50)
        _log(f"*** PUBLIC_WS_URL = {url} ***")
        _log("=" * 50)

        def _cleanup_cf():
            try:
                tunnel.stop()
            except Exception:
                pass

        atexit.register(_cleanup_cf)
    except Exception as e:
        _log(f"*** TUNNEL FAIL: {type(e).__name__}: {e} ***")
        _log("Server se chay khong co tunnel.")


def _find_cloudflared() -> str:
    local_exe = Path(__file__).parent / "cloudflared.exe"
    if local_exe.exists():
        return str(local_exe)
    local_no_ext = Path(__file__).parent / "cloudflared"
    if local_no_ext.exists():
        return str(local_no_ext)
    return "cloudflared"


# ─────────────────────────────────────────────────────────────
#  RUN BOTH ON IMPORT
# ─────────────────────────────────────────────────────────────
_log("=" * 50)
_log("BOOTSTRAP STARTING...")
_log("=" * 50)

_setup_ngrok()
_setup_cloudflare()

_log("=" * 50)
_log("BOOTSTRAP DONE - passing to server")
_log("=" * 50)