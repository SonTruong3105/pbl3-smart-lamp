"""Helper lấy thời gian hiện tại."""
from datetime import datetime

WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
               "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def get_current_time_str() -> str:
    now = datetime.now()
    return now.strftime(
        f"Bây giờ là %H:%M, ngày %d/%m/%Y ({WEEKDAYS_VI[now.weekday()]})."
    )
