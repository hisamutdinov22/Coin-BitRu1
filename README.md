# Coin BitRu — Render-ready Telegram bot + server

Структура проекта уже подготовлена для Render: `run.py` и папка `app/` находятся в корне репозитория.

## Render

Создай **Web Service** из GitHub-репозитория.

- Root Directory: оставить пустым
- Environment: Docker
- Dockerfile Path: `./Dockerfile`
- Docker Build Context Directory: `.`

В **Environment** добавь:

```text
BOT_TOKEN=токен_из_BotFather
PAYMENT_PROVIDER_TOKEN=токен_платежного_провайдера
ADMIN_IDS=твой_Telegram_ID
CHANNEL_USERNAME=@Coin_BitRu
CHANNEL_URL=https://t.me/Coin_BitRu
WEB_HOST=0.0.0.0
WEB_PORT=8080
```

После сохранения: **Manual Deploy → Deploy latest commit**.

Проверка сервера:

`https://<твой-сервис>.onrender.com/health`

## GitHub

При загрузке проекта содержимое этого архива нужно загрузить **в корень** репозитория. Не помещай весь проект в отдельную папку `add`.

В корне должны быть видны одновременно:

```text
app/
run.py
Dockerfile
requirements.txt
docker-compose.yml
.env.example
README.md
```

Не добавляй настоящий `.env` или секретные токены в GitHub.
