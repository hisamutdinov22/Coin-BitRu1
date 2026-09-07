# Замена файлов app/

Заменить в GitHub только эти 4 файла:

- `app/bot.py`
- `app/db.py`
- `app/services.py`
- `app/server.py`

Причины исправлений:
- устранена гонка SQLite при одновременном `init_db()` из сервера и бота;
- `profile`/`/start` больше не падают из-за `None`;
- восстановление энергии считается от последнего обновления, а не от даты создания;
- Mini App API использует исправленные функции тапа/улучшения;
- запуск polling делает `delete_webhook()` перед `getUpdates`.

После Commit changes Render обычно запустит новый deploy автоматически. Если Auto Deploy отключён: `Deploys -> Manual Deploy -> Deploy latest commit`.

Важно: `TelegramConflictError` остаётся, если один и тот же `BOT_TOKEN` одновременно используется другим запущенным экземпляром. Старый Render-сервис/локальный процесс с этим токеном должен быть остановлен.
