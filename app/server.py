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

# Корень проекта
BASE_DIR = Path(__file__).resolve().parent.parent
MINIAPP_DIR = BASE_DIR / "miniapp"
ASSETS_DIR = MINIAPP_DIR / "assets"

app = FastAPI(
    title="Coin BitRu",
    version="2.2.0"
)


# =========================
# STATIC MINI APP
# =========================

# Ассеты отдельно
if ASSETS_DIR.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=ASSETS_DIR),
        name="assets"
    )

# Вся папка miniapp
if MINIAPP_DIR.exists():
    app.mount(
        "/miniapp",
        StaticFiles(directory=MINIAPP_DIR),
        html=True,
        name="miniapp"
    )


# =========================
# STARTUP
# =========================

@app.on_event("startup")
async def startup() -> None:
    await init_db()


# =========================
# MINI APP MAIN PAGE
# =========================

@app.get("/", include_in_schema=False)
async def root():
    """
    Главная страница сайта = Telegram Mini App
    """
    index = MINIAPP_DIR / "index.html"

    if not index.exists():
        return JSONResponse(
            {
                "status": "error",
                "message": "Mini App index.html не найден",
                "expected_path": str(index)
            },
            status_code=404
        )

    return FileResponse(index)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "Coin BitRu"
    }


# Дополнительный прямой путь
@app.get("/app", include_in_schema=False)
async def open_app():
    index = MINIAPP_DIR / "index.html"

    if not index.exists():
        raise HTTPException(
            status_code=404,
            detail="Mini App не найден"
        )

    return FileResponse(index)


# =========================
# TELEGRAM AUTH
# =========================

def validate_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(
            status_code=401,
            detail="Откройте мини-приложение из Telegram."
        )

    pairs = dict(
        parse_qsl(
            init_data,
            keep_blank_values=True
        )
    )

    recv_hash = pairs.pop("hash", "")

    if not recv_hash:
        raise HTTPException(
            status_code=401,
            detail="Неверные данные Telegram."
        )

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(pairs.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        settings.bot_token.encode(),
        hashlib.sha256
    ).digest()

    calc_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(
        calc_hash,
        recv_hash
    ):
        raise HTTPException(
            status_code=401,
            detail="Проверка Telegram не пройдена."
        )

    try:
        auth_date = int(
            pairs.get("auth_date", "0")
        )

        if auth_date and time.time() - auth_date > 86400:
            raise HTTPException(
                status_code=401,
                detail="Сессия Telegram устарела. Откройте Mini App заново."
            )

        return json.loads(
            pairs["user"]
        )

    except (
        KeyError,
        ValueError,
        json.JSONDecodeError
    ):
        raise HTTPException(
            status_code=401,
            detail="Данные Telegram повреждены."
        )


async def auth_user(init_data: str):
    tg = validate_init_data(init_data)

    user = await profile(
        int(tg["id"])
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Сначала нажмите /start в боте."
        )

    return user


# =========================
# MODELS
# =========================

class WithdrawIn(BaseModel):
    usd: float
    destination: str


# =========================
# USER PROFILE
# =========================

@app.get("/api/me")
async def me(
    x_telegram_init_data: str = Header(default="")
):
    user = await auth_user(
        x_telegram_init_data
    )

    user = await restore_energy(
        user.id
    )

    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,

        "coins": user.coins,

        "usd": user.coins /
        settings.coins_per_usd,

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
                - user.last_daily_claim
                .replace(tzinfo=None)
                .timestamp()
            ) < 20 * 3600
        ),
    }


# =========================
# TASKS
# =========================

@app.get("/api/tasks")
async def api_tasks(
    x_telegram_init_data: str = Header(default="")
):
    user = await auth_user(
        x_telegram_init_data
    )

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
                "done": await task_status(
                    user.id,
                    task.id
                ),
            }
            for task in tasks
        ]
    }
