import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from .config import settings
from .db import Session, Task, init_db
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
MINIAPP_DIR = BASE_DIR / "miniapp"

app = FastAPI(title="Coin BitRu", version="2.2.0")

# Static Telegram Mini App
if MINIAPP_DIR.exists():
    app.mount(
        "/miniapp",
        StaticFiles(directory=str(MINIAPP_DIR), html=True),
        name="miniapp",
    )


@app.on_event("startup")
async def startup() -> None:
    await init_db()


@app.get("/")
async def root():
    return {"service": "Coin BitRu", "status": "ok"}


@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy"})


def validate_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(401, "Откройте мини-приложение из Telegram.")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    recv_hash = pairs.pop("hash", "")

    if not recv_hash:
        raise HTTPException(401, "Неверные данные Telegram.")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(pairs.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        settings.bot_token.encode(),
        hashlib.sha256,
    ).digest()

    calc_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calc_hash, recv_hash):
        raise HTTPException(401, "Проверка Telegram не пройдена.")

    try:
        auth_date = int(pairs.get("auth_date", "0"))

        if auth_date and time.time() - auth_date > 86400:
            raise HTTPException(
                401,
                "Сессия Telegram устарела. Откройте мини-приложение заново.",
            )

        return json.loads(pairs["user"])

    except (KeyError, ValueError, json.JSONDecodeError):
        raise HTTPException(401, "Данные Telegram повреждены.")


async def auth_user(init_data: str):
    tg = validate_init_data(init_data)
    user = await profile(int(tg["id"]))

    if not user:
        raise HTTPException(404, "Сначала нажмите /start в боте.")

    return user


class WithdrawIn(BaseModel):
    usd: float
    destination: str


@app.get("/api/me")
async def me(x_telegram_init_data: str = Header(default="")):
    user = await auth_user(x_telegram_init_data)
    user = await restore_energy(user.id)

    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "coins": user.coins,
        "usd": user.coins / settings.coins_per_usd,
        "tap_level": user.tap_level,
        "energy": user.energy,
        "max_energy": user.max_energy,
        "referrals": user.referrals,
        "topup_usd": user.topup_usd,
        "streak": user.streak,
        "daily_available": not bool(
            user.last_daily_claim
            and (
                time.time()
                - user.last_daily_claim.replace(tzinfo=None).timestamp()
            ) < 20 * 3600
        ),
    }


@app.get("/api/tasks")
async def api_tasks(x_telegram_init_data: str = Header(default="")):
    user = await auth_user(x_telegram_init_data)

    async with Session() as session:
        tasks = list(
            (
                await session.execute(
                    select(Task)
                    .where(Task.active.is_(True))
                    .order_by(Task.id)
                )
            ).scalars()
        )

    return {
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "reward_coins": task.reward_coins,
                "url": task.url,
                "kind": task.kind,
                "done": await task_status(user.id, task.id),
            }
            for task in tasks
        ]
    }


@app.post("/api/tap")
async def tap_api(x_telegram_init_data: str = Header(default="")):
    user = await auth_user(x_telegram_init_data)
    user = await do_tap(user.id)

    return {
        "coins": user.coins,
        "energy": user.energy,
        "max_energy": user.max_energy,
        "tap_level": user.tap_level,
    }


@app.post("/api/daily")
async def daily_api(x_telegram_init_data: str = Header(default="")):
    user = await auth_user(x_telegram_init_data)
    user = await daily_claim(user.id)

    return {
        "coins": user.coins,
        "streak": user.streak,
    }


@app.post("/api/tasks/{task_id}/complete")
async def complete_task_api(
    task_id: int,
    x_telegram_init_data: str = Header(default=""),
):
    user = await auth_user(x_telegram_init_data)
    return await complete_generic_task(user.id, task_id)


@app.get("/api/leaderboard")
async def leaderboard_api(x_telegram_init_data: str = Header(default="")):
    await auth_user(x_telegram_init_data)
    return {"users": await leaderboard()}


@app.post("/api/upgrade/tap")
async def upgrade_tap_api(x_telegram_init_data: str = Header(default="")):
    user = await auth_user(x_telegram_init_data)
    user = await upgrade_tap(user.id)

    return {
        "coins": user.coins,
        "tap_level": user.tap_level,
    }


@app.post("/api/withdraw")
async def withdraw_api(
    data: WithdrawIn,
    x_telegram_init_data: str = Header(default=""),
):
    user = await auth_user(x_telegram_init_data)
    return await create_withdrawal(
        user.id,
        data.usd,
        data.destination,
    )
