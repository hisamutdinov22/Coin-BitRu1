# Coin BitRu — запуск на Render с нуля

1. Создайте новый GitHub-репозиторий `Coin-BitRu`.
2. Загрузите содержимое этой папки в корень репозитория (не саму папку целиком).
3. В Render выберите **New → Web Service → Existing Repository**.
4. Репозиторий: `Coin-BitRu`, ветка: `main`.
5. Оставьте Root Directory пустым.
6. Dockerfile Path: `./Dockerfile`.
7. Docker Build Context Directory: `.`.
8. Health Check Path: `/health`.
9. В Environment добавьте `BOT_TOKEN`, `PAYMENT_PROVIDER_TOKEN`, `ADMIN_IDS`.
10. `CHANNEL_USERNAME` оставьте `@Coin_BitRu`.
11. Нажмите **Deploy latest commit**.

Сервис слушает Render `PORT` автоматически, а локально использует 8080.

Для SQLite на бесплатном Render постоянное хранение данных не гарантируется при пересоздании инстанса. Для реального проекта лучше подключить внешнюю PostgreSQL-базу.
