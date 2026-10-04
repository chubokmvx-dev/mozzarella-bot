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

## Команди

- `/plan 7` — контент-план на 7 днів (пости й Reels із фото продукту)
- фото + опис — картинка, підпис, вибір формату; кнопка «🚀 Опублікувати»
- `/dashboard` — дашборд із метриками (Telegram Mini App)
- `/report` — розбір результатів від Claude
- `/ig_connect`, `/ig_status` — підключення Instagram

## Змінні Railway

`BOT_TOKEN`, `ADMIN_ID`, `ANTHROPIC_API_KEY`, `DATABASE_URL`, `META_APP_ID`, `META_APP_SECRET`,
`PUBLIC_URL`, `PORT=8080`. Необов'язкові: `AUTO_PUBLISH=1` (публікувати без підтвердження),
`REMIND_HOUR` (година ранкового нагадування за Києвом, типово 9), `CLAUDE_MODEL`, `GRAPH_VERSION`.

## Фонові задачі

- метрики постів: через 24 год, 7 днів і поточні (оновлюються щогодини), далі показуються в дашборді
- нагадування: вранці та о 17:00, якщо на сьогодні за планом є пост без фото
- у понеділок після 10:00 бот сам надсилає тижневий розбір
