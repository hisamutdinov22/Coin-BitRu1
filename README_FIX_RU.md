# Исправление Coin BitRu для Render

Заменить в GitHub:
- `app/db.py`
- `app/server.py`
- `Dockerfile`

После Commit changes сделать новый Deploy в Render.

Исправления:
- таблица `tasks` создаётся до первого запроса;
- запуск БД защищён от гонки двух инициализаций;
- существующая БД не удаляется;
- Mini App копируется внутрь Docker-образа;
- `/miniapp` и API доступны в контейнере.
