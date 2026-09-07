from datetime import datetime, timezone, timedelta
from sqlalchemy import select, desc, func
from .db import Session, User, Payment, TaskCompletion, Withdrawal
from .config import settings

async def get_or_create_user(tg_user, referrer_id=None):
    async with Session() as s:
        user = await s.get(User, tg_user.id)
        if not user:
            valid_ref = referrer_id if referrer_id and referrer_id != tg_user.id else None
            user = User(id=tg_user.id, username=tg_user.username, first_name=tg_user.first_name, referrer_id=valid_ref)
            s.add(user)
            if valid_ref and await s.get(User, valid_ref):
                ref = await s.get(User, valid_ref)
                ref.referrals += 1
                ref.coins += settings.referral_reward_coins
                if ref.referrals == 5 and ref.referral_paid == 0:
                    ref.referral_paid = 1
                    ref.coins += settings.referral_5_bonus_usd * settings.coins_per_usd
            await s.commit()
        return user

async def profile(user_id):
    async with Session() as s: return await s.get(User, user_id)

async def tap(user_id):
    async with Session() as s:
        u=await s.get(User,user_id)
        if not u or u.energy<=0: return 0,u
        gain=u.tap_level
        u.energy-=1; u.coins+=gain
        await s.commit(); return gain,u

async def restore_energy(user_id):
    async with Session() as s:
        u=await s.get(User,user_id)
        if not u: return None
        now=datetime.now(timezone.utc)
        if u.energy < u.max_energy:
            elapsed=(now-u.created_at).total_seconds()
            u.energy=min(u.max_energy, u.energy + int(elapsed/15))
        await s.commit(); return u

async def upgrade_tap(user_id):
    async with Session() as s:
        u=await s.get(User,user_id)
        if not u: return False,u
        cost=int(1000*(1.8**(u.tap_level-1)))
        if u.coins<cost: return False,u
        u.coins-=cost; u.tap_level+=1; u.max_energy=min(1000,u.max_energy+10); u.energy=u.max_energy
        await s.commit(); return True,u

async def daily_claim(user_id):
    async with Session() as s:
        u=await s.get(User,user_id)
        now=datetime.now(timezone.utc)
        if u.last_daily_claim and (now-u.last_daily_claim).total_seconds()<20*3600: return False,u,0
        if u.last_daily_claim and (now-u.last_daily_claim).total_seconds()<=48*3600: u.streak=min(7,u.streak+1)
        else: u.streak=1
        rewards=[1000,2500,5000,7500,10000,20000,50000]
        reward=rewards[u.streak-1]
        u.coins+=reward; u.last_daily_claim=now
        await s.commit(); return True,u,reward

async def mark_task(user_id, task_id):
    async with Session() as s:
        c=await s.scalar(select(TaskCompletion).where(TaskCompletion.user_id==user_id,TaskCompletion.task_id==task_id))
        if c: return False,0
        from .db import Task
        t=await s.get(Task,task_id)
        if not t or not t.active:return False,0
        if t.kind=='channel':
            return None,t.reward_coins
        if t.kind=='taps': return None,t.reward_coins
        if t.kind=='referrals': return None,t.reward_coins
        s.add(TaskCompletion(user_id=user_id,task_id=task_id));
        u=await s.get(User,user_id); u.coins+=t.reward_coins
        await s.commit(); return True,t.reward_coins

async def complete_generic_task(user_id, task_id):
    async with Session() as s:
        from .db import Task
        t=await s.get(Task,task_id)
        if not t:return False,0,'notfound'
        c=await s.scalar(select(TaskCompletion).where(TaskCompletion.user_id==user_id,TaskCompletion.task_id==task_id))
        if c:return False,0,'done'
        u=await s.get(User,user_id)
        if t.kind=='taps' and u.coins < 100: return False,t.reward_coins,'condition'
        if t.kind=='referrals' and u.referrals < 3:return False,t.reward_coins,'condition'
        s.add(TaskCompletion(user_id=user_id,task_id=task_id)); u.coins+=t.reward_coins
        await s.commit();return True,t.reward_coins,'ok'

async def task_status(user_id, task_id):
    async with Session() as s:
        c=await s.scalar(select(TaskCompletion).where(TaskCompletion.user_id==user_id,TaskCompletion.task_id==task_id))
        return bool(c)

async def add_payment(user_id, amount_usd, currency, tg_charge, provider_charge, payload):
    async with Session() as s:
        exists=await s.scalar(select(Payment).where(Payment.telegram_charge_id==tg_charge))
        if exists:return False
        p=Payment(user_id=user_id,amount_minor=int(amount_usd*100),currency=currency,telegram_charge_id=tg_charge,provider_charge_id=provider_charge,payload=payload)
        s.add(p);u=await s.get(User,user_id);u.topup_usd += amount_usd
        await s.commit();return True

async def create_withdrawal(user_id, usd, destination):
    coins=int(round(usd*settings.coins_per_usd))
    async with Session() as s:
        u=await s.get(User,user_id)
        if not u:return False,'Пользователь не найден'
        if u.topup_usd < settings.withdraw_topup_min_usd:return False,f'Вывод доступен после пополнения на ${settings.withdraw_topup_min_usd:.0f}.'
        if usd < settings.withdraw_min_usd:return False,f'Минимум для вывода ${settings.withdraw_min_usd:.0f}.'
        if u.coins<coins:return False,'Недостаточно коинов.'
        u.coins-=coins;s.add(Withdrawal(user_id=user_id,usd=usd,coins=coins,destination=destination));await s.commit();return True,'Заявка создана.'

async def leaderboard(limit=10):
    async with Session() as s:
        return list((await s.execute(select(User).order_by(desc(User.coins)).limit(limit))).scalars())

async def tournament(limit=10):
    return await leaderboard(limit)
