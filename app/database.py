from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import config

DATABASE_URL = f"sqlite+aiosqlite:///{config.db_path}"

engine = create_async_engine(
    DATABASE_URL, echo=False, connect_args={"check_same_thread": False}
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)
Base = declarative_base()


async def init_db():
    from app import models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_messages_session_id_id "
            "ON messages (session_id, id)"
        )
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_sessions_device_id_id "
            "ON sessions (device_id, id)"
        )
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_devices_last_seen "
            "ON devices (last_seen)"
        )


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session