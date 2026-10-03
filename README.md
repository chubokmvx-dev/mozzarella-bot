# mozzarella-bot

Telegram-бот для Instagram-магазину «mozzarella»: Claude пише контент-план, бот присилає кожен пост на перевірку, ти підтверджуєш, скасовуєш або правиш текстом.

## Команди

- `/plan 7` — контент-план на 7 днів
- `/plan 7 більше рецептів` — з побажанням

Кнопки під кожним постом: ✅ Підтвердити · ✏️ Змінити · ❌ Скасувати.

## Запуск на Railway

1. Створи бота в @BotFather, збережи токен.
2. Дізнайся свій Telegram ID (наприклад, через @userinfobot).
3. Railway → New Project → Deploy from GitHub repo → обери цей репозиторій.
4. У проєкті додай Postgres (New → Database → PostgreSQL).
5. У змінних сервісу бота (Variables) додай:
   - `BOT_TOKEN`
   - `ADMIN_ID`
   - `ANTHROPIC_API_KEY`
   - `DATABASE_URL` (посилання на змінну з Postgres)
   - `CLAUDE_MODEL` (необов'язково)
6. Start command вже прописаний у `railway.json`: `python bot.py`.

Ключі й токени зберігай тільки у змінних Railway, у репозиторій їх не коміть.

## Локально

```
pip install -r requirements.txt
cp .env.example .env   # заповни значення
python bot.py
```

## Що далі

- Публікація в Instagram (Graph API) за розкладом
- Збір метрик через 24 год і 7 днів
- Тижневий аналіз від Claude і дашборд (Telegram Mini App)
