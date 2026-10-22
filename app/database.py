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


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session