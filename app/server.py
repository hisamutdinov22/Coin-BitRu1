import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from .config import settings
from .db import Session, Task
from .services import (
    profile,
    restore_energy,
    tap as do_tap,
    daily_claim,
    task_status,
    complete_generic_task,
    leaderboard,
    create_withdrawal,
    upgrade_tap,
)

BASE_DIR = Path(__file__).resolve().parent.parent
MINIAPP_DIR = BASE_DIR / 'miniapp'

app = FastAPI(title='Coin BitRu Server', version='1.2.0')
if MINIAPP_DIR.exists():
    app.mount('/miniapp', StaticFiles(directory=MINIAPP_DIR), name='miniapp')


@app.get('/')
async def root():
    return {'service': 'Coin BitRu', 'status': 'ok'}


@app.get('/health')
async def health():
    return JSONResponse({'status': 'healthy'})


@app.get('/miniapp')
async def miniapp():
    if not (MINIAPP_DIR / 'index.html').exists():
        raise HTTPException(404, 'Mini App не найден.')
    return FileResponse(MINIAPP_DIR / 'index.html')


def validate_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(401, 'Откройте мини-приложение из Telegram.')
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    recv_hash = pairs.pop('hash', '')
    if not recv_hash:
        raise HTTPException(401, 'Неверные данные Telegram.')
    data_check_string = '\n'.join(f'{key}={value}' for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b'WebAppData', settings.bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, recv_hash):
        raise HTTPException(401, 'Проверка Telegram не пройдена.')
    try:
        auth_date = int(pairs.get('auth_date', '0'))
        if auth_date and time.time() - auth_date > 86400:
            raise HTTPException(401, 'Сессия Telegram устарела. Откройте мини-приложение заново.')
        return json.loads(pairs['user'])
    except (KeyError, ValueError, json.JSONDecodeError):
        raise HTTPException(401, 'Данные пользователя Telegram повреждены.')


async def auth_user(init_data: str):
    tg = validate_init_data(init_data)
    user = await profile(int(tg['id']))
    if not user:
        raise HTTPException(404, 'Сначала нажмите /start в боте.')
    return user


class WithdrawIn(BaseModel):
    usd: float
    destination: str


@app.get('/api/me')
async def me(x_telegram_init_data: str = Header(default='')):
    user = await auth_user(x_telegram_init_data)
    user = await restore_energy(user.id)
    return {
        'id': user.id,
        'username': user.username,
        'first_name': user.first_name,
        'coins': user.coins,
        'usd': user.coins / settings.coins_per_usd,
        'tap_level': user.tap_level,
        'energy': user.energy,
        'max_energy': user.max_energy,
        'referrals': user.referrals,
        'topup_usd': user.topup_usd,
        'streak': user.streak,
        'daily_available': not bool(
            user.last_daily_claim and
            (time.time() - user.last_daily_claim.timestamp()) < 20 * 3600
        ),
    }


@app.post('/api/tap')
async def api_tap(x_telegram_init_data: str = Header(default='')):
    user = await auth_user(x_telegram_init_data)
    await restore_energy(user.id)
    gain, user = await do_tap(user.id)
    if not user or gain <= 0:
        raise HTTPException(400, 'Недостаточно энергии.')
    return {
        'gain': gain,
        'user': {
            'coins': user.coins,
            'energy': user.energy,
            'max_energy': user.max_energy,
            'tap_level': user.tap_level,
            'usd': user.coins / settings.coins_per_usd,
        },
    }


@app.get('/api/daily')
async def api_daily(x_telegram_init_data: str = Header(default='')):
    user = await auth_user(x_telegram_init_data)
    rewards = [1000, 2500, 5000, 7500, 10000, 20000, 50000]
    next_streak = 1 if user.streak >= 7 else (user.streak + 1 if user.streak else 1)
    available = not bool(
        user.last_daily_claim and
        (time.time() - user.last_daily_claim.timestamp()) < 20 * 3600
    )
    return {'streak': user.streak, 'reward': rewards[next_streak - 1], 'available': available}


@app.post('/api/daily/claim')
async def api_daily_claim(x_telegram_init_data: str = Header(default='')):
    user = await auth_user(x_telegram_init_data)
    ok, user, reward = await daily_claim(user.id)
    return {'ok': ok, 'message': 'Награда получена!' if ok else 'Сегодня награда уже получена.', 'reward': reward}


@app.post('/api/upgrade')
async def api_upgrade(x_telegram_init_data: str = Header(default='')):
    user = await auth_user(x_telegram_init_data)
    ok, user = await upgrade_tap(user.id)
    return {'ok': ok, 'message': 'Уровень улучшен!' if ok else 'Недостаточно коинов.'}


@app.get('/api/tasks')
async def api_tasks(x_telegram_init_data: str = Header(default='')):
    user = await auth_user(x_telegram_init_data)
    async with Session() as s:
        tasks = list((await s.execute(select(Task).where(Task.active.is_(True)).order_by(Task.id))).scalars())
    return {
        'tasks': [
            {
                'id': task.id,
                'title': task.title,
                'reward_coins': task.reward_coins,
                'url': task.url,
                'kind': task.kind,
                'done': await task_status(user.id, task.id),
            }
            for task in tasks
        ]
    }


@app.post('/api/tasks/{task_id}/claim')
async def api_task_claim(task_id: int, x_telegram_init_data: str = Header(default='')):
    user = await auth_user(x_telegram_init_data)
    async with Session() as s:
        task = await s.get(Task, task_id)
    if not task or not task.active:
        raise HTTPException(404, 'Задание не найдено.')
    if task.kind == 'channel':
        raise HTTPException(400, 'Проверку подписки выполни через Telegram-бота.')
    ok, reward, status = await complete_generic_task(user.id, task_id)
    if not ok:
        message = 'Условие ещё не выполнено.' if status == 'condition' else 'Задание уже выполнено.'
        raise HTTPException(400, message)
    return {'ok': True, 'message': f'+{reward:,} COIN'.replace(',', ' '), 'reward': reward}


@app.get('/api/refs')
async def api_refs(x_telegram_init_data: str = Header(default='')):
    user = await auth_user(x_telegram_init_data)
    from aiogram import Bot
    bot = Bot(settings.bot_token)
    try:
        me = await bot.get_me()
        link = f'https://t.me/{me.username}?start=ref_{user.id}'
    finally:
        await bot.session.close()
    return {
        'referrals': user.referrals,
        'reward_coins': settings.referral_reward_coins,
        'bonus_usd': settings.referral_5_bonus_usd,
        'link': link,
    }


@app.get('/api/leaders')
async def api_leaders(x_telegram_init_data: str = Header(default='')):
    await auth_user(x_telegram_init_data)
    users = await leaderboard(20)
    return {'users': [{'name': u.username and '@' + u.username or u.first_name or str(u.id), 'coins': u.coins} for u in users]}


@app.get('/api/tournament')
async def api_tournament(x_telegram_init_data: str = Header(default='')):
    await auth_user(x_telegram_init_data)
    users = await leaderboard(20)
    return {
        'prize_usd': settings.tournament_prize_usd,
        'users': [{'name': u.username and '@' + u.username or u.first_name or str(u.id), 'coins': u.coins} for u in users],
    }


@app.post('/api/withdraw')
async def api_withdraw(body: WithdrawIn, x_telegram_init_data: str = Header(default='')):
    user = await auth_user(x_telegram_init_data)
    ok, message = await create_withdrawal(user.id, body.usd, body.destination.strip())
    if not ok:
        raise HTTPException(400, message)
    return {'ok': True, 'message': 'Заявка на вывод создана и отправлена на ручную проверку.'}
