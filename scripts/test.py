"""Fix register/unregister device trong esp32_ws.py."""
import shutil
import sys
from datetime import datetime
from pathlib import Path

path = Path("app/routes/esp32_ws.py")
if not path.exists():
    print(f"ERROR: không tìm thấy {path}")
    sys.exit(1)

src = path.read_text(encoding="utf-8")

# ── Check đã patch chưa ──
if "from app.core.broadcast_hub import register_device" in src:
    print("ℹ️  Register device đã có sẵn — bỏ qua")
    sys.exit(0)

# ── Backup ──
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
bak = f"{path}.bak_v2fix_{stamp}"
shutil.copy(path, bak)
print(f"📦 Backup: {bak}")

# ── Detect line ending ──
has_crlf = "\r\n" in src
NL = "\r\n" if has_crlf else "\n"
print(f"📝 Line ending: {'CRLF' if has_crlf else 'LF'}")

# ── Patch 1: Register sau handler creation ──
old_reg = (
    "        transport = WebSocketTransport(ws)" + NL +
    "        handler = ESP32ConnectionHandler(transport, session_id, device_id)" + NL
)
new_reg = (
    "        transport = WebSocketTransport(ws)" + NL +
    "        handler = ESP32ConnectionHandler(transport, session_id, device_id)" + NL +
    "        try:" + NL +
    "            from app.core.broadcast_hub import register_device" + NL +
    "            register_device(device_id)" + NL +
    "        except Exception: pass" + NL
)

if old_reg not in src:
    print("❌ Register anchor NOT found")
    print("   Tìm 'transport = WebSocketTransport(ws)' trong file để xác nhận format")
    sys.exit(1)

src = src.replace(old_reg, new_reg, 1)
print("✅ Register on connect: inserted")

# ── Patch 2: Unregister trong finally ──
old_unreg = (
    "    finally:" + NL +
    "        if process_task and not process_task.done(): process_task.cancel()" + NL +
    "        if handler is not None:" + NL +
    "            try: await handler.abort()" + NL +
    "            except Exception: pass" + NL
)
new_unreg = (
    "    finally:" + NL +
    "        if process_task and not process_task.done(): process_task.cancel()" + NL +
    "        if handler is not None:" + NL +
    "            try: await handler.abort()" + NL +
    "            except Exception: pass" + NL +
    "        try:" + NL +
    "            from app.core.broadcast_hub import unregister_device" + NL +
    "            unregister_device(device_id)" + NL +
    "        except Exception: pass" + NL
)

if old_unreg not in src:
    print("❌ Finally anchor NOT found")
    sys.exit(1)

src = src.replace(old_unreg, new_unreg, 1)
print("✅ Unregister on disconnect: inserted")

# ── Write ──
path.write_text(src, encoding="utf-8")
print(f"💾 Written: {path}")

# ── Verify ──
verify_src = path.read_text(encoding="utf-8")
checks = {
    "register_device(device_id)": "register_device(device_id)" in verify_src,
    "unregister_device(device_id)": "unregister_device(device_id)" in verify_src,
}
all_ok = all(checks.values())
for name, ok in checks.items():
    print(f"  {'✅' if ok else '❌'} {name}")

# ── Import test ──
print("\n=== Import test ===")
import subprocess
result = subprocess.run(
    [sys.executable, "-c", "import app.main; print('IMPORT_OK')"],
    capture_output=True, text=True,
)
# Loguru ghi log ra stderr — chỉ cần check stdout + exit code
if result.returncode == 0 and "IMPORT_OK" in result.stdout:
    print("✅ app.main import OK")
else:
    print("❌ Import failed")
    print("stdout:", result.stdout[-500:])
    print("stderr:", result.stderr[-500:])
    sys.exit(1)

print("\n✅ DONE — restart server: python run.py")