"""Greeting module — Câu chào tự nhiên, time-aware, có Signature."""

import random
import re
from datetime import datetime

# 🌟 CÂU CHÀO SIGNATURE (Đặc trưng của Đèn)
# Bạn có thể sửa lại các câu này theo ý thích!
SIGNATURE_REPLIES = [
    "Chào bạn, hệ thống Đèn đã sẵn sàng.",
    "Chào bạn, Đèn đang nghe đây. Bạn cần gì cứ nói nhé.",
    "Chào bạn, tôi là Đèn. Rất vui được đồng hành cùng bạn.",
    "Chào bạn, Đèn đây ạ.",
]

# Giới thiệu bản thân (khi user nói "chào đèn" hoặc tương tự)
INTRO_REPLIES = [
    "Chào bạn, mình là Đèn đây! Bạn cần gì cứ gọi mình nhé.",
    "Chào bạn! Mình là Đèn, sống trong chiếc đèn bàn này. Rất vui được gặp bạn.",
    "Chào bạn! Mình là cô đèn nhỏ của bạn đây. Hôm nay bạn thế nào?",
]

# Chào đơn giản, ngắn
SIMPLE_REPLIES = [
    "Chào bạn!",
    "Ơ, chào bạn!",
    "Chào nhé!",
    "Hế lô, chào bạn!",
    "Chào bạn, mình nghe nè!",
]

# Chào + mở câu chuyện
WARM_REPLIES = [
    "Chào bạn! Hôm nay thế nào?",
    "Chào nhé, có gì vui không bạn?",
    "Chào bạn, bạn tới rồi, cần gì cứ nói nha!",
]

# Time-aware
TIME_AWARE = {
    "morning": ["Chào buổi sáng! Hôm nay bạn dậy sớm ghê.", "Chào buổi sáng, ngày mới tốt lành nhé!"],
    "noon": ["Chào buổi trưa! Ăn cơm chưa bạn?", "Chào bạn, trưa rồi, nhớ ăn uống đầy đủ nha."],
    "afternoon": ["Chào buổi chiều! Chiều nay thế nào?", "Chào buổi chiều nhé, công việc ổn không bạn?"],
    "evening": ["Chào buổi tối! Hôm nay có gì vui không?", "Chào buổi tối nhé, thư giãn chút đi bạn."],
    "night": ["Chào bạn, khuya rồi đó, chưa ngủ sao?", "Chào bạn, đêm rồi nhớ nghỉ sớm nha."],
}

EXPLICIT_TIME = {
    "sáng": "morning", "sáng sớm": "morning", "trưa": "noon",
    "chiều": "afternoon", "tối": "evening", "đêm": "night", "khuya": "night",
}

# "chào đèn" / "đèn ơi" → giới thiệu
INTRO_TRIGGERS = re.compile(r"\b(chào\s+đèn|chào\s+em|đèn\s+ơi|hey\s+đèn|hế\s+lô\s+đèn)\b", re.IGNORECASE)

def _get_time_slot() -> str:
    h = datetime.now().hour
    if 5 <= h < 11: return "morning"
    if 11 <= h < 13: return "noon"
    if 13 <= h < 18: return "afternoon"
    if 18 <= h < 22: return "evening"
    return "night"

def build_greeting(user_text: str, time_aware: bool = True) -> str:
    """Sinh câu chào tự nhiên dựa vào context user + giờ hiện tại."""
    q = (user_text or "").lower().strip()

    # 1. "chào đèn" / "đèn ơi" → Giới thiệu (hoặc Signature)
    if INTRO_TRIGGERS.search(q):
        # 50% dùng câu Signature, 50% dùng câu Giới thiệu tự nhiên
        return random.choice(SIGNATURE_REPLIES + INTRO_REPLIES)

    # 2. Mention buổi cụ thể → time-aware tương ứng
    for kw, slot in EXPLICIT_TIME.items():
        if kw in q:
            return random.choice(TIME_AWARE[slot])

    # 3. Thỉnh thoảng dùng câu Signature (20% xác suất) để tạo dấu ấn
    if random.random() < 0.2:
        return random.choice(SIGNATURE_REPLIES)

    # 4. Time-aware theo giờ hiện tại (60% xác suất)
    if time_aware and random.random() < 0.6:
        return random.choice(TIME_AWARE[_get_time_slot()])

    # 5. Mix simple + warm
    return random.choice(SIMPLE_REPLIES + WARM_REPLIES)
