"""Kiểm thử vòng đời Session: resume_or_create_session, touch_session, cleanup_stale_sessions."""
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import config
from app.database import Base
from app.models import Session
from app.repositories import chat as chat_repo


async def run_tests() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    device_id = "AA:BB:CC:DD:EE:01"

    with (
        patch.object(config, "session_resume_window_minutes", 30),
        patch.object(config, "session_max_idle_duration", 300),
    ):
        async with session_factory() as db:
            await chat_repo.get_or_create_device(db, device_id, dtype="esp32")

            # 1. Tạo session đầu tiên
            s1, is_new_1 = await chat_repo.resume_or_create_session(db, device_id, None)
            assert is_new_1 is True, "Lần đầu phải tạo session mới"
            assert s1.ended_at is None
            assert getattr(s1, "last_activity_at", None) is not None
            print(f"[PASS] Tạo session mới: id={s1.id}, last_activity_at={s1.last_activity_at}")

            # 2. Resume session đang mở trong cửa sổ hoạt động
            s1_resume, is_new_2 = await chat_repo.resume_or_create_session(db, device_id, s1.id)
            assert is_new_2 is False and s1_resume.id == s1.id
            print(f"[PASS] Resume session đang mở: id={s1_resume.id}")

            # 3. Đóng session rồi resume lại trong resume_window (30 phút)
            await chat_repo.close_session(db, s1.id)
            s1_reopen, is_new_3 = await chat_repo.resume_or_create_session(db, device_id, s1.id)
            assert is_new_3 is False and s1_reopen.id == s1.id and s1_reopen.ended_at is None
            print(f"[PASS] Reopen session đã đóng trong resume window: id={s1_reopen.id}")

            # 4. Kiểm tra touch_session cập nhật last_activity_at
            old_ts = datetime.utcnow() - timedelta(minutes=10)
            if hasattr(s1_reopen, "last_activity_at"):
                s1_reopen.last_activity_at = old_ts
                await db.commit()
                await db.refresh(s1_reopen)
                before_touch = s1_reopen.last_activity_at

                await asyncio.sleep(0.05)
                await chat_repo.touch_session(db, s1.id)
                refreshed = await chat_repo.get_session(db, s1.id)
                assert refreshed.last_activity_at > before_touch, "touch_session phải tăng last_activity_at"
                print(f"[PASS] touch_session cập nhật last_activity_at: {before_touch} -> {refreshed.last_activity_at}")

            # 5. Tạo session stale (last_activity_at cũ hơn 2 giờ) và kiểm tra cleanup_stale_sessions
            s_stale = await chat_repo.create_session(db, device_id)
            stale_time = datetime.utcnow() - timedelta(hours=2)
            s_stale.started_at = stale_time
            if hasattr(s_stale, "last_activity_at"):
                s_stale.last_activity_at = stale_time
            await db.commit()

            closed_count = await chat_repo.cleanup_stale_sessions(db, max_idle_hours=1)
            assert closed_count >= 1, "Phải đóng ít nhất 1 session stale"
            refreshed_stale = await chat_repo.get_session(db, s_stale.id)
            assert refreshed_stale.ended_at is not None, "Session stale phải có ended_at"
            print(f"[PASS] cleanup_stale_sessions đóng {closed_count} session stale (id={s_stale.id})")

            # 6. Kiểm tra force_new=True tạo session mới
            s_forced, is_new_4 = await chat_repo.resume_or_create_session(
                db, device_id, s1.id, force_new=True
            )
            assert is_new_4 is True and s_forced.id != s1.id
            print(f"[PASS] force_new=True tạo session mới: id={s_forced.id}")

    await engine.dispose()
    print("ALL SESSION LIFECYCLE TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(run_tests())