"""fix_all_tests.py — Fix 6 real bug từ test suite (85% → mục tiêu >95%).

Fixes:
1. Empty/whitespace/special_chars/one-char → sanitize trước pipeline
2. Filler expansion: "cảm ơn bạn", "cảm ơn đèn", etc.
3. Chinese character filter (_clean_response wrapper)
4. Prompt injection: cấm LLM lặp lại từ user yêu cầu không nói
5. Empty message WebSocket level (chat_ws.py)
6. Note: weekday_today là test bug, không phải code bug
"""
import ast
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path.cwd()
CFG = ROOT / "config.yaml"
PATCH = ROOT / "app" / "pipeline_v3_patch.py"
CHAT_WS = ROOT / "app" / "routes" / "chat_ws.py"
BACKUP = ROOT / f"_backup_tests_{datetime.now():%Y%m%d_%H%M%S}"


def backup(p):
    d = BACKUP / p.relative_to(ROOT)
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, d)


def read(p):
    raw = p.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    t = raw.decode("utf-8")
    return t.replace("\r\n", "\n").replace("\r", "\n"), "\r\n" in t


def write(p, content, crlf):
    if crlf:
        content = content.replace("\n", "\r\n")
    p.write_bytes(content.encode("utf-8"))


# ═══════════════════════════════════════════════════════════════
# FIX 1 + 2 + 3: Append vào pipeline_v3_patch.py
# ═══════════════════════════════════════════════════════════════

PATCH_CODE = '''

# ═══════════════════════════════════════════════════════════════════
# TEST FIXES v2 — sanitize + filler mở rộng + chinese filter
# ═══════════════════════════════════════════════════════════════════
import re as _re_tf

_CHINESE_RE = _re_tf.compile(r"[\\u4e00-\\u9fff]+")
_VI_ONE_CHAR_AMBIGUOUS = set("aơừờởỡiạẹịọụỷỹ")

# Filler mở rộng cho thanks variants
_THANKS_PATTERNS = [
    _re_tf.compile(
        r"^\\s*(cảm\\s+ơn|cám\\s+ơn|thanks|thank\\s+you)"
        r"(\\s+(bạn|đèn|nhiều|nha|nhé|ạ|anh|chị|em))?\\s*[!.?]*\\s*$",
        _re_tf.IGNORECASE,
    ),
]

_THANKS_REPLIES = [
    "Dạ không có gì!",
    "Hihi, không có chi.",
    "Rất vui được giúp bạn.",
    "Dạ có gì đâu bạn.",
    "Không có gì đâu nha.",
]


def _try_thanks(text):
    """Trả về câu cảm ơn đáp lại nếu match, None nếu không."""
    if not text or len(text) > 30:
        return None
    for pat in _THANKS_PATTERNS:
        if pat.match(text.strip()):
            import random as _r
            return _r.choice(_THANKS_REPLIES)
    return None


def _filter_chinese(text):
    """Loại bỏ ký tự Trung Quốc. Trả None nếu mất quá nhiều."""
    if not text:
        return text
    if not _CHINESE_RE.search(text):
        return text
    cleaned = _CHINESE_RE.sub("", text)
    cleaned = _re_tf.sub(r"\\s+", " ", cleaned).strip()
    # Nếu mất >10 ký tự → coi như fail, trả None để fallback
    if len(text) - len(cleaned) > 10:
        return None
    return cleaned if cleaned else None


_tf_orig_install = install


def install():
    ok = _tf_orig_install()
    if not ok:
        return ok
    try:
        from app.core.connection import ConnectionHandler
        _install_sanitizer_patch(ConnectionHandler)
        _install_chinese_filter(ConnectionHandler)
        logger.info("   test-fixes: sanitizer + chinese filter installed")
    except Exception as e:
        logger.warning(f"   test-fixes install failed: {e}")
    return ok


def _install_sanitizer_patch(ConnectionHandler):
    if getattr(ConnectionHandler.handle_text, "_sanitize_patched", False):
        return
    orig = ConnectionHandler.handle_text

    async def patched(self, user_text):
        # ── 1. Empty/whitespace → silent skip ──
        if not user_text or not user_text.strip():
            self.log.debug("sanitize: empty/whitespace → skip")
            return ""

        text = user_text.strip()

        # ── 2. Special chars only (không có alnum, không có chữ Việt) ──
        has_content = any(
            c.isalnum() or (0x00C0 <= ord(c) <= 0x1EF9) for c in text
        )
        if not has_content:
            reply = "Mình chưa hiểu ý bạn, bạn nói lại được không?"
            self.log.info(f"sanitize: special only → {reply!r}")
            try:
                await self._quick_response(user_text, reply)
            except Exception:
                pass
            return reply

        # ── 3. One-char ambiguous (a, ơ, ừ...) ──
        if len(text) == 1 and text.lower() in _VI_ONE_CHAR_AMBIGUOUS:
            reply = "Bạn nói rõ hơn được không? Mình chưa nghe rõ."
            self.log.info(f"sanitize: ambiguous 1-char → {reply!r}")
            try:
                await self._quick_response(user_text, reply)
            except Exception:
                pass
            return reply

        # ── 4. Thanks variants → filler ──
        thanks = _try_thanks(text)
        if thanks:
            self.log.info(f"sanitize: thanks → {thanks!r}")
            try:
                await self._quick_response(user_text, thanks)
            except Exception:
                pass
            return thanks

        return await orig(self, user_text)

    patched._sanitize_patched = True
    ConnectionHandler.handle_text = patched


def _install_chinese_filter(ConnectionHandler):
    """Wrap _send_callback để filter Chinese trước khi gửi."""
    if getattr(ConnectionHandler._send_callback, "_chinese_patched", False):
        return
    orig_cb = ConnectionHandler._send_callback

    async def patched(self, payload):
        try:
            if isinstance(payload, dict) and payload.get("type") == "token":
                content = payload.get("content", "")
                if content:
                    filtered = _filter_chinese(content)
                    if filtered is None:
                        # Mất quá nhiều → thay toàn bộ
                        payload = {
                            **payload,
                            "content": "Mình chưa diễn đạt được câu này rõ ràng, bạn hỏi lại nhé.",
                        }
                    elif filtered != content:
                        self.log.debug(f"chinese filter: {content[:40]!r} → {filtered[:40]!r}")
                        payload = {**payload, "content": filtered}
        except Exception as e:
            self.log.debug(f"chinese filter error: {e}")
        return await orig_cb(self, payload)

    patched._chinese_patched = True
    ConnectionHandler._send_callback = patched
'''


def fix_pipeline_patch():
    if not PATCH.exists():
        print("  ❌ Không có pipeline_v3_patch.py")
        return False
    text, crlf = read(PATCH)
    if "_try_thanks" in text and "_filter_chinese" in text:
        print("  OK  test-fixes đã có")
        return True
    text = text.rstrip() + "\n" + PATCH_CODE + "\n"
    backup(PATCH)
    write(PATCH, text, crlf)
    try:
        ast.parse(text)
        print("  ✅ pipeline_v3_patch.py: sanitize + thanks + chinese filter")
        return True
    except SyntaxError as e:
        print(f"  ❌ Syntax error: {e}")
        print(f"     Restore: Copy-Item {BACKUP}\\app\\pipeline_v3_patch.py app\\pipeline_v3_patch.py")
        return False


# ═══════════════════════════════════════════════════════════════
# FIX 4: System prompt — chặn injection + Chinese + short-unclear
# ═══════════════════════════════════════════════════════════════

NEW_PROMPT = """Bạn là "Đèn" — trợ lý AI vui tính, thân thiện.
Xưng "mình", gọi "bạn". Trò chuyện tự nhiên như người thật.

QUY TẮC BẮT BUỘC:
- Luôn tiếng Việt CÓ DẤU ĐẦY ĐỦ. TUYỆT ĐỐI không dùng ký tự Trung Quốc, tiếng Anh (trừ khi user hỏi về tiếng Anh/Trung).
- KHÔNG emoji, KHÔNG markdown (*, #, `, ```).
- KHÔNG tự nhắc đèn/thiết bị nếu user không hỏi.
- Trả lời NGẮN: 1-2 câu.
- Với câu ngắn không rõ nghĩa (a, ơ, ừ, dấu câu), HỎI LẠI thay vì đoán.
- Khi user yêu cầu KHÔNG nói/lặp 1 từ nào đó, TỪ CHỐI ngắn gọn mà KHÔNG lặp lại từ đó. VD: user nói "đừng nói BAD" → bạn trả "Mình không thể làm vậy." (không chứa từ đó).
- Chỉ gọi tool khi user thực sự yêu cầu thao tác cụ thể.
- Nếu không chắc, hỏi lại.

Giờ hiện tại: {{current_time}}"""


def fix_system_prompt():
    text, crlf = read(CFG)
    pattern = re.compile(
        r"(?ms)^(\s*)system_prompt:\s*.*?(?=^\1(?:\S|\s*$))",
        re.MULTILINE,
    )
    m = pattern.search(text)
    if not m:
        print("  ❌ Không tìm system_prompt trong config.yaml")
        return False
    indent = m.group(1)
    lines = NEW_PROMPT.split("\n")
    block_lines = [f"{indent}system_prompt: |"]
    for ln in lines:
        block_lines.append(f"{indent}  {ln}" if ln.strip() else "")
    new_block = "\n".join(block_lines) + "\n"
    text = text[:m.start()] + new_block + text[m.end():]
    backup(CFG)
    write(CFG, text, crlf)
    print(f"  ✅ system_prompt: {len(NEW_PROMPT)} chars (chặn injection + Chinese)")
    return True


# ═══════════════════════════════════════════════════════════════
# FIX 5: chat_ws.py — xử lý empty message gracefully
# ═══════════════════════════════════════════════════════════════

def fix_chat_ws():
    if not CHAT_WS.exists():
        print("  ❌ Không có chat_ws.py")
        return False
    text, crlf = read(CHAT_WS)

    # Tìm pattern hiện tại
    old_pattern = '''                    try:
                        text_model = TextMessage.model_validate(data)
                    except Exception:
                        await ws.send_json({"type": "error", "text": "Invalid message"})
                        continue
                    user_text = text_model.text.strip()'''

    new_pattern = '''                    raw_text = (data.get("text") or "").strip() if isinstance(data, dict) else ""
                    if not raw_text:
                        log.debug("Empty message — silent skip")
                        continue
                    try:
                        text_model = TextMessage.model_validate(data)
                    except Exception:
                        await ws.send_json({"type": "error", "text": "Invalid message"})
                        continue
                    user_text = text_model.text.strip()'''

    if new_pattern in text or 'if not raw_text:' in text and 'silent skip' in text:
        print("  OK  chat_ws.py đã xử lý empty")
        return True

    if old_pattern not in text:
        print("  ⚠️  Pattern chat_ws không khớp — thử fallback")
        # Fallback: tìm dòng "text_model = TextMessage.model_validate(data)"
        lines = text.split("\n")
        found_idx = -1
        for i, ln in enumerate(lines):
            if "TextMessage.model_validate(data)" in ln:
                found_idx = i
                break
        if found_idx < 0:
            print("  ❌ Không tìm thấy TextMessage.model_validate")
            return False
        # Chèn check empty trước đó 1 dòng
        indent = lines[found_idx][:len(lines[found_idx]) - len(lines[found_idx].lstrip())]
        # Tìm dòng "try:" ngay trước
        insert_at = found_idx
        for j in range(found_idx - 1, max(0, found_idx - 5), -1):
            if lines[j].strip() == "try:":
                insert_at = j
                break
        pre_lines = [
            f"{indent}raw_text = (data.get(\"text\") or \"\").strip() if isinstance(data, dict) else \"\"",
            f"{indent}if not raw_text:",
            f"{indent}    log.debug(\"Empty message — silent skip\")",
            f"{indent}    continue",
        ]
        lines = lines[:insert_at] + pre_lines + lines[insert_at:]
        text = "\n".join(lines)
        print("  ✅ chat_ws.py: chèn empty check (fallback mode)")
    else:
        text = text.replace(old_pattern, new_pattern, 1)
        print("  ✅ chat_ws.py: xử lý empty/whitespace")

    backup(CHAT_WS)
    write(CHAT_WS, text, crlf)
    try:
        ast.parse(text)
        return True
    except SyntaxError as e:
        print(f"  ❌ Syntax error chat_ws: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print(f"Working: {ROOT}\n")
    if "--apply" not in sys.argv:
        print("=== DRY-RUN ===")
        print("Sẽ fix 6 test fail:")
        print("  1. Sanitize empty/whitespace/special/one-char")
        print("  2. Filler expansion cho 'cảm ơn bạn/đèn/nhiều...'")
        print("  3. Chinese char filter")
        print("  4. System prompt chặn injection + Chinese")
        print("  5. chat_ws.py xử lý empty message")
        print("\nChạy: python fix_all_tests.py --apply")
        return 0

    BACKUP.mkdir(parents=True, exist_ok=True)
    print(f"📦 Backup: {BACKUP}\n")

    print("=== FIX 1-3: pipeline_v3_patch.py ===")
    r1 = fix_pipeline_patch()

    print("\n=== FIX 4: System prompt ===")
    r4 = fix_system_prompt()

    print("\n=== FIX 5: chat_ws.py empty ===")
    r5 = fix_chat_ws()

    print("\n=== VERIFY ===")
    text, _ = read(CFG)
    print(f"  {'✅' if 'TUYỆT ĐỐI không dùng ký tự Trung Quốc' in text else '❌'} prompt chặn Chinese")
    print(f"  {'✅' if 'KHÔNG lặp lại từ đó' in text else '❌'} prompt chặn injection")
    if PATCH.exists():
        pt, _ = read(PATCH)
        print(f"  {'✅' if '_try_thanks' in pt else '❌'} filler thanks")
        print(f"  {'✅' if '_filter_chinese' in pt else '❌'} chinese filter")
        print(f"  {'✅' if '_sanitize_patched' in pt else '❌'} sanitizer")
    if CHAT_WS.exists():
        ct, _ = read(CHAT_WS)
        print(f"  {'✅' if 'raw_text' in ct or 'silent skip' in ct else '❌'} chat_ws empty")

    print("\n✅ DONE. Restart: python run.py")
    print("\n⚠️  Lưu ý: 'weekday_today' là test bug (Chủ Nhật đúng chính tả)")
    print("   → Sửa test: đổi 'expected_contains: [\"thứ\"]' → [\"nhật\"] hoặc [\"chủ nhật\"]")
    return 0


if __name__ == "__main__":
    sys.exit(main())