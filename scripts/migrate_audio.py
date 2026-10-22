"""Thêm cột audio_path vào bảng messages (SQLite)."""
import sqlite3
from pathlib import Path


DB_PATH = Path("data/xiaozhi.db")


def main():
    if not DB_PATH.exists():
        print(f"❌ Không tìm thấy DB: {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    try:
        # Kiểm tra cột đã tồn tại chưa
        cursor = conn.execute("PRAGMA table_info(messages)")
        columns = [row[1] for row in cursor.fetchall()]

        if "audio_path" in columns:
            print("✅ Cột audio_path đã tồn tại, bỏ qua")
        else:
            conn.execute("ALTER TABLE messages ADD COLUMN audio_path TEXT")
            conn.commit()
            print("✅ Đã thêm cột audio_path")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()