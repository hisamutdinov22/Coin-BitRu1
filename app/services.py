from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import Payment, Session, Task, TaskCompletion, User, Withdrawal


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_or_create_user(tg_user, referrer_id=None):
    async with Session() as session:
        user = await session.get(User, tg_user.id)
        if user:
            changed = False
            if user.username != getattr(tg_user, "username", None):
                user.username = getattr(tg_user, "username", None)
                changed = True
            if user.first_name != getattr(tg_user, "first_name", None):
                user.first_name = getattr(tg_user, "first_name", None)
                changed = True
            if changed:
                await session.commit()
            return user

        valid_ref = referrer_id if referrer_id and referrer_id != tg_user.id else None
        if valid_ref:
            ref = await session.get(User, valid_ref)
            if not ref:
                valid_ref = None

        now = utcnow()
        user = User(
            id=tg_user.id,
            username=getattr(tg_user, "username", None),
            first_name=getattr(tg_user, "first_name", None),
            referrer_id=valid_ref,
            created_at=now,
            energy_updated_at=now,
            coins=0,
            tap_level=1,
            energy=100,
            max_energy=100,
            referrals=0,
            referral_paid=0,
            topup_usd=0,
            streak=0,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            return await _get_existing_user(tg_user.id)

        if valid_ref:
            ref = await session.get(User, valid_ref)
            if ref:
                ref.referrals += 1
                ref.coins += settings.referral_reward_coins
                if ref.referrals == 5 and ref.referral_paid == 0:
                    ref.referral_paid = 1
                    ref.coins += settings.referral_5_bonus_usd * settings.coins_per_usd

        await session.commit()
        return user


async def _get_existing_user(user_id: int):
    async with Session() as session:
        return await session.get(User, user_id)


async def profile(user_id):
    async with Session() as session:
        return await session.get(User, user_id)


async def restore_energy(user_id):
    async with Session() as session:
        user = await session.get(User, user_id)
        if not user:
            return None
        now = utcnow()
        updated = user.energy_updated_at or user.created_at or now
        elapsed = max(0, int((now - updated).total_seconds()))
        if elapsed >= 15 and user.energy < user.max_energy:
            user.energy = min(user.max_energy, user.energy + elapsed // 15)
        user.energy_updated_at = now
        await session.commit()
        return user


async def tap(user_id):
    async with Session() as session:
        user = await session.get(User, user_id)
        if not user:
            return 0, None
        if user.energy <= 0:
            return 0, user
        gain = max(1, user.tap_level)
        user.energy -= 1
        user.coins += gain
        user.energy_updated_at = utcnow()
        await session.commit()
        return gain, user


async def upgrade_tap(user_id):
    async with Session() as session:
        user = await session.get(User, user_id)
        if not user:
            return False, None
        cost = int(1000 * (1.8 ** max(0, user.tap_level - 1)))
        if user.coins < cost:
            return False, user
        user.coins -= cost
        user.tap_level += 1
        user.max_energy = min(1000, user.max_energy + 10)
        user.energy = user.max_energy
        user.energy_updated_at = utcnow()
        await session.commit()
        return True, user


async def daily_claim(user_id):
    async with Session() as session:
        user = await session.get(User, user_id)
        if not user:
            return False, None, 0
        now = utcnow()
        if user.last_daily_claim:
            hours = (now - user.last_daily_claim).total_seconds() / 3600
            if hours < 20:
                return False, user, 0
            user.streak = min(7, user.streak + 1) if hours <= 48 else 1
        else:
            user.streak = 1
        rewards = [1000, 2500, 5000, 7500, 10000, 20000, 50000]
        reward = rewards[user.streak - 1]
        user.coins += reward
        user.last_daily_claim = now
        await session.commit()
        return True, user, reward


async def task_status(user_id, task_id):
    async with Session() as session:
        completion = await session.scalar(
            select(TaskCompletion.id).where(
                TaskCompletion.user_id == user_id,
                TaskCompletion.task_id == task_id,
            )
        )
        return completion is not None


async def complete_generic_task(user_id, task_id):
    async with Session() as session:
        task = await session.get(Task, task_id)
        user = await session.get(User, user_id)
        if not task or not task.active:
            return False, 0, "notfound"
        if not user:
            return False, 0, "user"
        completion = await session.scalar(
            select(TaskCompletion.id).where(
                TaskCompletion.user_id == user_id,
                TaskCompletion.task_id == task_id,
            )
        )
        if completion:
            return False, task.reward_coins, "done"
        if task.kind == "taps" and user.coins < 100:
            return False, task.reward_coins, "condition"
        if task.kind == "referrals" and user.referrals < 3:
            return False, task.reward_coins, "condition"
        if task.kind == "channel":
            return False, task.reward_coins, "channel"
        session.add(TaskCompletion(user_id=user_id, task_id=task_id))
        user.coins += task.reward_coins
        await session.commit()
        return True, task.reward_coins, "ok"


async def add_payment(user_id, amount_usd, currency, tg_charge, provider_charge, payload):
    async with Session() as session:
        if await session.scalar(select(Payment.id).where(Payment.telegram_charge_id == tg_charge)):
            return False
        user = await session.get(User, user_id)
        if not user:
            return False
        session.add(Payment(
            user_id=user_id,
            amount_minor=int(round(amount_usd * 100)),
            currency=currency,
            telegram_charge_id=tg_charge,
            provider_charge_id=provider_charge or "",
            payload=payload or "",
        ))
        user.topup_usd += amount_usd
        await session.commit()
        return True


async def create_withdrawal(user_id, usd, destination):
    coins = int(round(usd * settings.coins_per_usd))
    async with Session() as session:
        user = await session.get(User, user_id)
        if not user:
            return False, "Пользователь не найден."
        if user.topup_usd < settings.withdraw_topup_min_usd:
            return False, f"Вывод доступен после пополнения на ${settings.withdraw_topup_min_usd:.0f}."
        if usd < settings.withdraw_min_usd:
            return False, f"Минимум для вывода ${settings.withdraw_min_usd:.0f}."
        if not destination or len(destination.strip()) < 8:
            return False, "Укажи корректные реквизиты для вывода."
        if user.coins < coins:
            return False, "Недостаточно коинов."
        user.coins -= coins
        session.add(Withdrawal(user_id=user_id, usd=usd, coins=coins, destination=destination.strip()))
        await session.commit()
        return True, "Заявка создана."


async def leaderboard(limit=10):
    async with Session() as session:
        return list((await session.execute(select(User).order_by(desc(User.coins)).limit(limit))).scalars())


async def tournament(limit=10):
    return await leaderboard(limit)
