#!/bin/bash
# patch-tools-filter.sh
# Rút gọn output của TẤT CẢ tools trước khi gửi LLM.
# Chỉ giữ title + snippet, bỏ JSON metadata, markdown, cắt độ dài.
#
# Usage:
#   bash patch-tools-filter.sh
#   bash patch-tools-filter.sh /path/to/Xiaozhi_server

set -e

ROOT="${1:-$(pwd)}"
cd "$ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m'

echo ""
echo -e "${CYAN}══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  PATCH TOOLS FILTER${NC}"
echo -e "${CYAN}  Bỏ JSON metadata + markdown, chỉ giữ thông tin hữu ích${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════════${NC}"
echo ""

# Verify
if [ ! -f "app/main.py" ]; then
    echo -e "${RED}❌ Không thấy app/main.py. Chạy từ thư mục dự án.${NC}"
    echo "   bash patch-tools-filter.sh /path/to/Xiaozhi_server"
    exit 1
fi

# Auto activate venv
if [ -d "venv" ] && [ -f "venv/bin/activate" ]; then
    echo -e "${GRAY}▶ Activate venv${NC}"
    source venv/bin/activate
fi

for f in app/core/providers/tools/impl.py app/core/providers/tools/registry.py; do
    if [ ! -f "$f" ]; then
        echo -e "${RED}❌ Không thấy: $f${NC}"
        exit 1
    fi
done

# Backup
STAMP=$(date +%Y%m%d_%H%M%S)
BK="_backup_tools_filter_$STAMP"
mkdir -p "$BK"
for f in app/core/providers/tools/impl.py app/core/providers/tools/registry.py; do
    cp "$f" "$BK/$(basename $f)"
done
echo -e "${GREEN}📦 Backup: $BK${NC}"
echo ""

echo -e "${YELLOW}[1/3] Patch impl.py${NC}"
echo -e "${YELLOW}[2/3] Patch registry.py${NC}"
echo -e "${YELLOW}[3/3] Verify + test${NC}"
echo ""

# ============================================================
# PATCH VIA PYTHON
# ============================================================
set +e
python3 << 'PYEOF'
from pathlib import Path
import sys

errors = []

# ---- impl.py: thêm _compact_text ----
impl_path = Path("app/core/providers/tools/impl.py")
text = impl_path.read_text(encoding="utf-8")

if "_compact_text" in text:
    print("   = impl.py: đã có _compact_text, skip")
else:
    anchor = '''def _clean_text(s: str) -> str:
    if not s: return ""
    s = html_mod.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\\s+", " ", s)
    return s.strip()
'''
    if anchor not in text:
        errors.append("impl.py: không tìm thấy _clean_text anchor (file đã bị sửa?)")
        print("   ❌ impl.py: không tìm thấy anchor")
    else:
        addition = '''

def _compact_text(text: str, max_chars: int = 1500) -> str:
    """Rút gọn output tool: parse JSON nếu có, bỏ metadata, clean markdown, cắt độ dài.

    Mục đích: tránh LLM bị ngộp vì JSON raw 12K chars từ web_search,
    hoặc bị distract bởi markdown/số thứ tự từ snippet.
    """
    if not text:
        return ""
    t = str(text)

    # 1. Parse JSON (Parallel/Tavily trả structured)
    try:
        import json as _json
        data = _json.loads(t)
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            lines = []
            for i, r in enumerate(data["results"][:3], 1):
                if not isinstance(r, dict):
                    continue
                title = (r.get("title") or r.get("name") or "").strip()
                content = (
                    r.get("content") or r.get("snippet") or r.get("description")
                    or r.get("body") or r.get("text") or r.get("answer") or ""
                ).strip()
                if not title and not content:
                    continue
                if len(content) > 300:
                    content = content[:300].rsplit(" ", 1)[0] + "..."
                block = f"[{i}] {title}" if title else f"[{i}]"
                if content:
                    block += f": {content}"
                lines.append(block)
            if lines:
                t = " | ".join(lines)
    except (ValueError, TypeError, KeyError):
        pass  # Không phải JSON

    # 2. Clean markdown + gộp whitespace
    t = re.sub(r"[#*_`>]+", "", t)
    t = re.sub(r"\\s+", " ", t)
    t = t.strip()

    # 3. Cắt độ dài
    if len(t) > max_chars:
        t = t[:max_chars].rsplit(" ", 1)[0] + "..."

    return t
'''
        text = text.replace(anchor, anchor + addition, 1)
        impl_path.write_text(text, encoding="utf-8")
        print("   ✅ impl.py: thêm _compact_text()")

# ---- registry.py: wrap execute_tool ----
reg_path = Path("app/core/providers/tools/registry.py")
text = reg_path.read_text(encoding="utf-8")

if "_compact_text(str(result)" in text:
    print("   = registry.py: đã wrap, skip")
else:
    old = '''    try:
        return await fn(**arguments)
    except TypeError as e:
        logger.error(f"Tool {name} sai tham số: {e} | args={arguments}")
        return f"Lỗi tham số cho {name}: {e}"
    except Exception as e:
        logger.exception(f"Tool {name} lỗi")
        return f"Lỗi khi chạy {name}: {e}"
'''
    new = '''    try:
        result = await fn(**arguments)
        # ✅ Compact: bỏ JSON metadata, markdown, cắt độ dài
        try:
            return _impl._compact_text(str(result), max_chars=1500)
        except AttributeError:
            return str(result)
    except TypeError as e:
        logger.error(f"Tool {name} sai tham số: {e} | args={arguments}")
        return f"Lỗi tham số cho {name}: {e}"
    except Exception as e:
        logger.exception(f"Tool {name} lỗi")
        return f"Lỗi khi chạy {name}: {e}"
'''
    if old not in text:
        errors.append("registry.py: không tìm thấy execute_tool pattern")
        print("   ❌ registry.py: không tìm thấy pattern")
    else:
        text = text.replace(old, new, 1)
        reg_path.write_text(text, encoding="utf-8")
        print("   ✅ registry.py: wrap execute_tool()")

if errors:
    print("")
    for e in errors:
        print(f"❌ {e}")
    sys.exit(1)
PYEOF
PY_EXIT=$?
set -e

if [ $PY_EXIT -ne 0 ]; then
    echo -e "${RED}❌ Patch fail → rollback${NC}"
    cp "$BK/impl.py" app/core/providers/tools/impl.py
    cp "$BK/registry.py" app/core/providers/tools/registry.py
    exit 1
fi

# ============================================================
# VERIFY
# ============================================================
echo ""
echo -e "${YELLOW}🔍 Verify syntax${NC}"
set +e
python3 -m py_compile app/core/providers/tools/impl.py
OK1=$?
python3 -m py_compile app/core/providers/tools/registry.py
OK2=$?
set -e

if [ $OK1 -eq 0 ] && [ $OK2 -eq 0 ]; then
    echo -e "${GREEN}   ✅ Syntax OK${NC}"
else
    echo -e "${RED}❌ Syntax error → rollback${NC}"
    cp "$BK/impl.py" app/core/providers/tools/impl.py
    cp "$BK/registry.py" app/core/providers/tools/registry.py
    exit 1
fi

# ============================================================
# TEST _compact_text
# ============================================================
echo ""
echo -e "${YELLOW}🧪 Test _compact_text${NC}"
set +e
python3 << 'TESTEOF'
import sys
sys.path.insert(0, ".")
try:
    from app.core.providers.tools.impl import _compact_text

    # Test 1: JSON Parallel
    sample_json = '''{"search_id":"abc123","results":[
        {"title":"Kết quả 1","content":"Nội dung mẫu 1 với nhiều thông tin hữu ích kéo dài nhiều dòng để test cắt."},
        {"title":"Kết quả 2","content":"Nội dung mẫu 2"},
        {"title":"Kết quả 3","content":"Nội dung mẫu 3"},
        {"title":"Kết quả 4","content":"Bị cắt vì chỉ lấy 3"}
    ]}'''
    r1 = _compact_text(sample_json, max_chars=500)
    assert "search_id" not in r1, "Còn metadata!"
    assert "Kết quả 1" in r1, "Mất title!"
    assert "Kết quả 4" not in r1, "Lấy quá 3 kết quả!"
    print(f"   ✅ JSON: {len(sample_json)} → {len(r1)} chars")

    # Test 2: Markdown
    r2 = _compact_text("### **Title**\nĐây là _text_ có `code` và **bold**.", max_chars=500)
    assert "#" not in r2 and "*" not in r2 and "`" not in r2
    print(f"   ✅ Markdown: {r2}")

    # Test 3: Cắt dài
    r3 = _compact_text("a " * 1000, max_chars=100)
    assert len(r3) <= 105
    print(f"   ✅ Long: 2000 → {len(r3)} chars")

    # Test 4: Empty
    r4 = _compact_text("", max_chars=100)
    assert r4 == ""
    print(f"   ✅ Empty input OK")

    print("   ✅ ALL PASS")
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
TESTEOF
TEST_EXIT=$?
set -e

if [ $TEST_EXIT -ne 0 ]; then
    echo -e "${YELLOW}⚠️  Test fail — patch giữ nguyên, kiểm tra tay${NC}"
fi

echo ""
echo -e "${CYAN}══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ HOÀN TẤT${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}📋 Thay đổi:${NC}"
echo "  ✅ impl.py: _compact_text()"
echo "     • Parse JSON → chỉ lấy 3 results đầu, title + snippet"
echo "     • Bỏ markdown (#, *, _, \`, >)"
echo "     • Cắt > 1500 chars"
echo "  ✅ registry.py: execute_tool() tự compact MỌI output"
echo ""
echo -e "${YELLOW}🚀 Test:${NC}"
echo "  pkill -f 'python run.py' && python run.py"
echo ""
echo "  Rồi thử các câu gây quá tải trước đây:"
echo "    'khái quát lịch sử trung quốc'"
echo "    'danh sách nền văn hóa thời đồ đá'"
echo "    'tin tức bóng đá hôm nay'"
echo "    'dự báo thời tiết Hà Nội 3 ngày'"
echo ""
echo -e "${YELLOW}📊 Log mong đợi:${NC}"
echo "  ← web_search: (1500 chars, KHÔNG có search_id)"
echo "  Extract #1-3 (thay vì 7+)"
echo "  ✅ Xong: N tokens, 2-3 câu"
echo ""
echo -e "${YELLOW}💾 Rollback:${NC}"
echo "  cp $BK/impl.py app/core/providers/tools/impl.py"
echo "  cp $BK/registry.py app/core/providers/tools/registry.py"
echo ""