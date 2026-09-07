from datetime import datetime, timezone

from sqlalchemy import desc, select

from .config import settings
from .db import Payment, Session, Task, TaskCompletion, User, Withdrawal


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_or_create_user(tg_user, referrer_id=None):
    async with Session() as s:
        user = await s.get(User, tg_user.id)
        if user:
            changed = False
            if user.username != tg_user.username:
                user.username = tg_user.username
                changed = True
            if user.first_name != tg_user.first_name:
                user.first_name = tg_user.first_name
                changed = True
            if changed:
                await s.commit()
            return user

        valid_ref = referrer_id if referrer_id and referrer_id != tg_user.id else None
        if valid_ref and not await s.get(User, valid_ref):
            valid_ref = None

        now = utcnow()
        user = User(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            referrer_id=valid_ref,
            created_at=now,
            energy_updated_at=now,
        )
        s.add(user)
        await s.flush()

        if valid_ref:
            ref = await s.get(User, valid_ref)
            if ref:
                ref.referrals += 1
                ref.coins += settings.referral_reward_coins
                if ref.referrals == 5 and ref.referral_paid == 0:
                    ref.referral_paid = 1
                    ref.coins += settings.referral_5_bonus_usd * settings.coins_per_usd

        await s.commit()
        return user


async def profile(user_id):
    async with Session() as s:
        return await s.get(User, user_id)


async def restore_energy(user_id):
    async with Session() as s:
        u = await s.get(User, user_id)
        if not u:
            return None

        now = utcnow()
        updated = u.energy_updated_at or u.created_at or now
        elapsed = max(0, int((now - updated).total_seconds()))
        if elapsed >= 15 and u.energy < u.max_energy:
            gained = elapsed // 15
            u.energy = min(u.max_energy, u.energy + gained)
        u.energy_updated_at = now
        await s.commit()
        return u


async def tap(user_id):
    async with Session() as s:
        u = await s.get(User, user_id)
        if not u:
            return 0, None
        if u.energy <= 0:
            return 0, u
        gain = max(1, u.tap_level)
        u.energy -= 1
        u.coins += gain
        u.energy_updated_at = utcnow()
        await s.commit()
        return gain, u


async def upgrade_tap(user_id):
    async with Session() as s:
        u = await s.get(User, user_id)
        if not u:
            return False, None
        cost = int(1000 * (1.8 ** (u.tap_level - 1)))
        if u.coins < cost:
            return False, u
        u.coins -= cost
        u.tap_level += 1
        u.max_energy = min(1000, u.max_energy + 10)
        u.energy = u.max_energy
        u.energy_updated_at = utcnow()
        await s.commit()
        return True, u


async def daily_claim(user_id):
    async with Session() as s:
        u = await s.get(User, user_id)
        if not u:
            return False, None, 0
        now = utcnow()
        if u.last_daily_claim:
            hours = (now - u.last_daily_claim).total_seconds() / 3600
            if hours < 20:
                return False, u, 0
            if hours <= 48:
                u.streak = min(7, u.streak + 1)
            else:
                u.streak = 1
        else:
            u.streak = 1

        rewards = [1000, 2500, 5000, 7500, 10000, 20000, 50000]
        reward = rewards[u.streak - 1]
        u.coins += reward
        u.last_daily_claim = now
        await s.commit()
        return True, u, reward


async def complete_generic_task(user_id, task_id):
    async with Session() as s:
        task = await s.get(Task, task_id)
        if not task or not task.active:
            return False, 0, 'notfound'
        user = await s.get(User, user_id)
        if not user:
            return False, 0, 'user'
        completion = await s.scalar(
            select(TaskCompletion).where(
                TaskCompletion.user_id == user_id,
                TaskCompletion.task_id == task_id,
            )
        )
        if completion:
            return False, 0, 'done'
        if task.kind == 'taps' and user.coins < 100:
            return False, task.reward_coins, 'condition'
        if task.kind == 'referrals' and user.referrals < 3:
            return False, task.reward_coins, 'condition'
        if task.kind == 'channel':
            return False, task.reward_coins, 'channel'

        s.add(TaskCompletion(user_id=user_id, task_id=task_id))
        user.coins += task.reward_coins
        await s.commit()
        return True, task.reward_coins, 'ok'


async def task_status(user_id, task_id):
    async with Session() as s:
        completion = await s.scalar(
            select(TaskCompletion).where(
                TaskCompletion.user_id == user_id,
                TaskCompletion.task_id == task_id,
            )
        )
        return bool(completion)


async def add_payment(user_id, amount_usd, currency, tg_charge, provider_charge, payload):
    async with Session() as s:
        exists = await s.scalar(select(Payment).where(Payment.telegram_charge_id == tg_charge))
        if exists:
            return False
        user = await s.get(User, user_id)
        if not user:
            return False
        s.add(
            Payment(
                user_id=user_id,
                amount_minor=int(round(amount_usd * 100)),
                currency=currency,
                telegram_charge_id=tg_charge,
                provider_charge_id=provider_charge or '',
                payload=payload or '',
            )
        )
        user.topup_usd += amount_usd
        await s.commit()
        return True


async def create_withdrawal(user_id, usd, destination):
    coins = int(round(usd * settings.coins_per_usd))
    async with Session() as s:
        user = await s.get(User, user_id)
        if not user:
            return False, 'Пользователь не найден.'
        if user.topup_usd < settings.withdraw_topup_min_usd:
            return False, f'Вывод доступен после пополнения на ${settings.withdraw_topup_min_usd:.0f}.'
        if usd < settings.withdraw_min_usd:
            return False, f'Минимум для вывода ${settings.withdraw_min_usd:.0f}.'
        if not destination or len(destination) < 8:
            return False, 'Укажи корректный адрес/реквизиты для вывода.'
        if user.coins < coins:
            return False, 'Недостаточно коинов.'
        user.coins -= coins
        s.add(Withdrawal(user_id=user_id, usd=usd, coins=coins, destination=destination.strip()))
        await s.commit()
        return True, 'Заявка создана.'


async def leaderboard(limit=10):
    async with Session() as s:
        return list((await s.execute(select(User).order_by(desc(User.coins)).limit(limit))).scalars())


async def tournament(limit=10):
    return await leaderboard(limit)
