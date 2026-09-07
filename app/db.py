from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    coins: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    tap_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    energy: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_energy: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    referrer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    referrals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    referral_paid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    topup_usd: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_daily_claim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_charge_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider_charge_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    payload: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    reward_coins: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="internal", nullable=False)
    url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TaskCompletion(Base):
    __tablename__ = "task_completions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    task_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    usd: Mapped[float] = mapped_column(Float, nullable=False)
    coins: Mapped[int] = mapped_column(BigInteger, nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)


engine = create_async_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
)
Session = async_sessionmaker(engine, expire_on_commit=False)

# run.py currently calls init_db() from both the FastAPI startup hook and the bot startup.
# This lock prevents those two startup paths from racing to create the same SQLite tables.
_init_lock = asyncio.Lock()
_initialized = False


async def init_db() -> None:
    global _initialized

    if _initialized:
        return

    async with _init_lock:
        if _initialized:
            return

        # SQLAlchemy's create_all checks for existing tables before creating them.
        # The process-local lock above also prevents two concurrent startup paths from
        # both observing a missing table and then racing to CREATE TABLE in SQLite.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Seed built-in tasks once. Existing task rows are preserved.
        async with Session() as session:
            existing_ids = set((await session.execute(select(Task.id))).scalars().all())
            defaults = [
                Task(
                    id=1,
                    title="Подписаться на канал Coin BitRu",
                    reward_coins=50_000,
                    kind="channel",
                    url=settings.channel_url,
                ),
                Task(
                    id=2,
                    title="Сделать 100 тапов",
                    reward_coins=10_000,
                    kind="taps",
                    url="",
                ),
                Task(
                    id=3,
                    title="Пригласить 3 друзей",
                    reward_coins=25_000,
                    kind="referrals",
                    url="",
                ),
            ]
            for task in defaults:
                if task.id not in existing_ids:
                    session.add(task)
            await session.commit()

        _initialized = True
