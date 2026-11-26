#!/usr/bin/env python3
"""
Fix Music Query Only — Sửa hàm music_search_query (không cắt mất tên bài).

Chức năng:
1. Sửa hàm music_search_query trong app/music.py.
2. Backup trước khi thay đổi.

Cách dùng:
    python fix_music_query_only.py --dry-run    # Chạy thử
    python fix_music_query_only.py --apply      # Thực hiện
    python fix_music_query_only.py --restore    # Khôi phục
"""

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
BACKUP_DIR = PROJECT_ROOT / f".backup_music_query_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

MUSIC_FILE = PROJECT_ROOT / "app" / "music.py"


def log(msg: str, level: str = "INFO"):
    colors = {"INFO": "\033[94m", "OK": "\033[92m", "WARN": "\033[93m", "ERROR": "\033[91m"}
    reset = "\033[0m"
    print(f"{colors.get(level, '')}[{level}]{reset} {msg}")


def backup_files():
    log(f"Đang backup vào {BACKUP_DIR}...")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if MUSIC_FILE.exists():
        rel_path = MUSIC_FILE.relative_to(PROJECT_ROOT)
        dst = BACKUP_DIR / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MUSIC_FILE, dst)
        log(f"  → Đã backup: {rel_path}", "OK")
        return True
    log(f"  → Không tìm thấy: {MUSIC_FILE}", "ERROR")
    return False


def restore_files():
    backups = sorted(PROJECT_ROOT.glob(".backup_music_query_*"))
    if not backups:
        log("Không tìm thấy backup nào!", "ERROR")
        return False
    latest = backups[-1]
    log(f"Đang khôi phục từ {latest}...")
    rel_path = MUSIC_FILE.relative_to(PROJECT_ROOT)
    backup_file = latest / rel_path
    if backup_file.exists():
        shutil.copy2(backup_file, MUSIC_FILE)
        log(f"  → Đã khôi phục: {rel_path}", "OK")
    log("Khôi phục hoàn tất!", "OK")
    return True


# ✅ SỬA: Dùng raw string (r"""...""") để tránh lỗi escape
NEW_MUSIC_QUERY_FUNC = r'''def music_search_query(text: str) -> Optional[str]:
    """Remove common Vietnamese playback phrasing before YouTube search.
    
    Cải thiện: chỉ cắt từ khóa ở ĐẦU câu, giữ nguyên tên bài hát.
    """
    if not isinstance(text, str):
        return None
    quoted = re.search(r'[\"“”‘’](.+?)[\"“”‘’]', text)
    if quoted:
        query = quoted.group(1).strip()
    else:
        # Chỉ cắt từ khóa ở ĐẦU câu (phát, mở, bật, nghe, play)
        query = re.sub(r"^(?:hãy\s+)?(?:phát|mở|bật|nghe|play)\s+", "", text, flags=re.I).strip()
        # Cắt các từ khóa phụ ở ĐẦU (bài hát, bài, nhạc)
        query = re.sub(r"^(?:(?:bài hát|bài|nhạc)\s+)+", "", query, flags=re.I).strip()
        # Cắt "ca sĩ", "trên youtube", "giúp tôi", "cho tôi nghe" ở CUỐI
        query = re.sub(r"\s+(?:ca sĩ|trên youtube|youtube|giúp tôi|cho tôi nghe)\s*$", "", query, flags=re.I).strip()
        # Cắt "nhé", "nha" ở cuối
        query = re.sub(r"\b(?:nhé|nha)\b$", "", query, flags=re.I).strip()
    return re.sub(r"\s+", " ", query).strip(" .,!?:;")[:160] or None'''


def fix_music_query(dry_run: bool = True) -> bool:
    if not MUSIC_FILE.exists():
        log(f"Không tìm thấy: {MUSIC_FILE}", "ERROR")
        return False

    content = MUSIC_FILE.read_text(encoding="utf-8")

    if "Cải thiện: chỉ cắt từ khóa ở ĐẦU câu" in content:
        log("  → music_search_query đã được sửa, bỏ qua", "WARN")
        return True

    if dry_run:
        log("  → [DRY-RUN] Sẽ sửa hàm music_search_query")
        return True

    try:
        pattern = re.compile(
            r'def music_search_query\(text: str\) -> Optional\[str\]:.*?(?=\n\ndef |\n\nclass |\Z)',
            re.DOTALL
        )
        if pattern.search(content):
            new_content = pattern.sub(lambda m: NEW_MUSIC_QUERY_FUNC, content)
            MUSIC_FILE.write_text(new_content, encoding="utf-8")
            log("  → Đã sửa hàm music_search_query", "OK")
        else:
            log("  → Không tìm thấy hàm music_search_query", "ERROR")
            return False
        return True
    except Exception as e:
        log(f"  → Lỗi: {e}", "ERROR")
        return False


def main():
    parser = argparse.ArgumentParser(description="Fix Music Query Only")
    parser.add_argument("--dry-run", action="store_true", help="Chạy thử")
    parser.add_argument("--apply", action="store_true", help="Thực hiện")
    parser.add_argument("--restore", action="store_true", help="Khôi phục")
    parser.add_argument("--no-backup", action="store_true", help="Không backup")
    args = parser.parse_args()

    if args.restore:
        restore_files()
        return

    if not args.dry_run and not args.apply:
        parser.print_help()
        print("\n⚠️  Bạn phải chọn --dry-run hoặc --apply")
        return

    dry_run = args.dry_run

    if args.apply and not args.no_backup:
        if not backup_files():
            return

    log("\n" + "=" * 60)
    log("🎵 FIX MUSIC QUERY ONLY", "INFO")
    log("=" * 60)
    log(f"\n📁 File: {MUSIC_FILE.relative_to(PROJECT_ROOT)}", "INFO")
    log("\n📝 BƯỚC 1: Sửa hàm music_search_query", "INFO")
    fix_music_query(dry_run=dry_run)
    log("\n" + "=" * 60)

    if dry_run:
        log("💡 Đây là chế độ DRY-RUN. Chưa có thay đổi nào được áp dụng.", "INFO")
        log("   Chạy lại với --apply để thực hiện thay đổi.", "INFO")
    else:
        log(f"✅ Hoàn tất! Backup tại: {BACKUP_DIR}", "OK")
        log("   Nếu có lỗi, chạy: python fix_music_query_only.py --restore", "INFO")
        log("\n📋 CÁC BƯỚC TIẾP THEO:", "INFO")
        log("   1. Xóa cache nhạc cũ: Remove-Item -Path data/music_cache -Recurse -Force")
        log("   2. Xóa __pycache__: Get-ChildItem -Include __pycache__ -Recurse | Remove-Item -Recurse -Force")
        log("   3. Khởi động lại server: python run.py")
        log("   4. Thử: 'phát bài Em Kể Anh Nghe của Quốc Thiên'")
    log("=" * 60)


if __name__ == "__main__":
    main()