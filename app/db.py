from datetime import datetime, timezone
from typing import Optional
import asyncio

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    coins: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    tap_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    energy: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_energy: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    referrer_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    referrals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    referral_paid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    topup_usd: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
    last_daily_claim: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    energy_updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_charge_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider_charge_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    payload: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)


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
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    task_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)


class Withdrawal(Base):
    __tablename__ = "withdrawals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    usd: Mapped[float] = mapped_column(Float, nullable=False)
    coins: Mapped[int] = mapped_column(BigInteger, nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)


engine = create_async_engine(settings.database_url, future=True, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)
_init_lock = asyncio.Lock()


async def init_db() -> None:
    """Create all missing tables and seed defaults; safe on every restart."""
    async with _init_lock:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        except OperationalError as exc:
            # A second initializer may race on SQLite; continue if tables already exist.
            if "already exists" not in str(exc).lower():
                raise

        defaults = [
            (1, "Подписаться на канал Coin BitRu", 50_000, "channel", settings.channel_url),
            (2, "Сделать 100 тапов", 10_000, "taps", ""),
            (3, "Пригласить 3 друзей", 25_000, "referrals", ""),
        ]

        async with Session() as session:
            # Query is intentionally after create_all so an old database lacking `tasks`
            # is upgraded automatically without deleting existing users/payments.
            existing_ids = set((await session.execute(select(Task.id))).scalars().all())
            for task_id, title, reward, kind, url in defaults:
                if task_id not in existing_ids:
                    session.add(Task(id=task_id, title=title, reward_coins=reward, kind=kind, url=url))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
