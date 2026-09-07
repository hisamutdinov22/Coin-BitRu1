from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, Text, ForeignKey
from sqlalchemy.ext.asyncio import AsyncAttrs, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from .config import settings


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    coins: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    tap_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    energy: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_energy: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    referrer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id'), nullable=True)
    referrals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    referral_paid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    topup_usd: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_daily_claim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    energy_updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class Payment(Base):
    __tablename__ = 'payments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    currency: Mapped[str] = mapped_column(String(8))
    amount_minor: Mapped[int] = mapped_column(Integer)
    telegram_charge_id: Mapped[str] = mapped_column(String(255), unique=True)
    provider_charge_id: Mapped[str] = mapped_column(String(255), default='')
    payload: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    reward_coins: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(32), default='internal')
    url: Mapped[str] = mapped_column(String(500), default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TaskCompletion(Base):
    __tablename__ = 'task_completions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class Withdrawal(Base):
    __tablename__ = 'withdrawals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    usd: Mapped[float] = mapped_column(Float)
    coins: Mapped[int] = mapped_column(BigInteger)
    destination: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default='pending')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class Setting(Base):
    __tablename__ = 'settings'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


engine = create_async_engine(settings.database_url, future=True)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create missing tables without failing when they already exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as s:
        existing = {row[0] for row in (await s.execute(__import__('sqlalchemy').select(Task.id))).all()}
        defaults = [
            Task(id=1, title='Подписаться на канал Coin BitRu', reward_coins=50000, kind='channel', url=settings.channel_url),
            Task(id=2, title='Сделать 100 тапов', reward_coins=10000, kind='taps'),
            Task(id=3, title='Пригласить 3 друзей', reward_coins=25000, kind='referrals'),
        ]
        for task in defaults:
            if task.id not in existing:
                s.add(task)
        await s.commit()
