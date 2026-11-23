"""Bộ lọc Intent & dựng OpenAI Tool Schema theo ngữ cảnh câu hỏi."""
import re
from app.core.providers.tools.unified import FunctionRegistry

PURE_CHAT_HINTS = re.compile(
    r"\b(xin\s+chào|chào\s+bạn|chào\s+đèn|chào\s+em|hế\s+lô|hê\s+lô|"
    r"hello|hi\b|hey|"
    r"cảm\s+ơn|thanks|thank\s+you|tạm\s+biệt|bye|goodbye|"
    r"vui|buồn|mệt|khỏe|hạnh\s+phúc|lo\s+lắng|chán|"
    r"bạn\s+là\s+ai|tên\s+bạn|bạn\s+tên|"
    r"kể\s+chuyện|nói\s+về|tâm\s+sự|"
    r"yêu|thương|ghét|giận|nhớ)\b",
    re.IGNORECASE,
)

TOOL_SIGNAL_RE = re.compile(
    r"\b(đèn|lịch|lịch\s+trình|lịch\s+hẹn|sự\s+kiện|"
    r"thời\s+tiết|nhiệt\s+độ|độ\s+ẩm|ánh\s+sáng|không\s+khí|"
    r"tin\s+tức|giá\s+vàng|giá|tỷ\s+giá|bitcoin|"
    r"bật|tắt|mở|đóng|đặt|thêm|xóa|sửa|"
    r"cảm\s+biến|hiện\s+diện|pm2\.?5|bụi\s+mịn|"
    r"mấy\s+giờ|thứ\s+mấy|ngày\s+mấy|hôm\s+nay|ngày\s+mai|"
    r"nhạc|bài\s+hát|phát\s+nhạc)\b",
    re.IGNORECASE,
)

MUSIC_REQUEST_RE = re.compile(
    r"(?i)\b(nhạc|bài\s+hát|music|youtube|playlist)\b|"
    r"\b(phát|nghe|bật|mở)\s+(?:bài|nhạc)",
    re.IGNORECASE,
)


def is_music_request(text: str) -> bool:
    return bool(text and MUSIC_REQUEST_RE.search(text))


def looks_like_pure_chat(text: str) -> bool:
    if not text:
        return False
    if not PURE_CHAT_HINTS.search(text):
        return False
    if TOOL_SIGNAL_RE.search(text):
        return False
    return True


def build_tool_schema(query: str, domain: str = "chat", log=None) -> list:
    """Dựng danh sách tool schema tối giản khớp với yêu cầu người dùng."""
    normalized = " ".join((query or "").lower().split())
    allowed = set()
    has_calendar_intent = bool(re.search(
        r"\b(?:lịch(?:\s+(?:trình|hẹn|học|làm\s+việc))?|sự\s+kiện|cuộc\s+hẹn)\b",
        normalized,
    )) and not re.search(r"\b(?:âm lịch|dương lịch)\b", normalized)

    if has_calendar_intent:
        allowed.add("list_calendar")
    if has_calendar_intent and re.search(r"\b(thêm|tạo|đặt)\b", normalized):
        allowed.add("add_calendar_event")
    if has_calendar_intent and re.search(r"\b(sửa|đổi|cập nhật)\b", normalized):
        allowed.add("update_calendar_event")
    if has_calendar_intent and re.search(r"\b(xóa|hủy|huỷ)\b", normalized):
        allowed.add("delete_calendar_event")
    if re.search(
        r"\b(bật|mở|tắt|đóng|đèn|độ sáng|màu đèn|nhiệt độ màu|nhiệt màu|chuyển màu|đổi màu|"
        r"ánh sáng trắng|trắng sáng|màu trắng|ánh sáng vàng|màu vàng|ánh sáng ấm|màu ấm|trung tính|kelvin|"
        r"hẹn giờ|đặt lịch|màn hình|hiển thị)\b",
        normalized,
    ):
        allowed.update({"control_light", "set_schedule", "update_display"})
    if re.search(r"\b(thời tiết|dự báo|mưa|nhiệt độ ngoài trời|trời hôm nay)\b", normalized):
        allowed.add("get_weather")
    if re.search(
        r"\b(nhiệt độ(?!\s+màu)(?:\s+phòng)?|độ ẩm|ánh sáng(?!\s+(?:trắng|vàng|ấm|lạnh|trung tính))|cảm biến|không khí|pm2?\.?5|bụi mịn|hiện diện)\b",
        normalized,
    ) and not re.search(r"ngoài trời|thời tiết|dự báo", normalized):
        allowed.add("get_environment")
    if re.search(r"\b(mấy giờ|giờ rồi|thứ mấy|ngày hôm nay|hôm nay là ngày|ngày mai là ngày|âm lịch)\b", normalized):
        allowed.add("get_current_time")
    if re.search(r"\b(tìm kiếm|tra cứu|tin tức|thời sự|giá vàng|tỷ giá|bitcoin|mới nhất)\b", normalized):
        allowed.add("web_search")
    if is_music_request(normalized):
        allowed.add("play_music")

    # Fallback khi IntentLLM đã phân loại domain == "device" nhưng regex không khớp do ASR nghe nhầm
    if domain == "device" and not allowed:
        allowed.update({"control_light", "get_environment"})

    # Đảm bảo giữ direct_answer nếu có trong registry khi ở chế độ hội thoại
    if domain == "chat" and not allowed:
        allowed.add("direct_answer")

    tools = FunctionRegistry(allowed).to_openai_schema()
    if log:
        log.info(f"🔧 Macro Tools ({len(tools)}): {[t['function']['name'] for t in tools]}")
    return tools