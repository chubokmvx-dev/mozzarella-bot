import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

# Instagram / Meta (необов'язкові, поки не підключено публікацію)
META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_USER_TOKEN = os.getenv("META_USER_TOKEN", "")  # короткий токен лише для першого підключення
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v23.0")

# Публічна адреса сервісу на Railway (для посилань на фото/відео) і режим авто-публікації
PUBLIC_URL = os.getenv("PUBLIC_URL", "")
PORT = int(os.getenv("PORT", "8080"))
AUTO_PUBLISH = os.getenv("AUTO_PUBLISH", "0") == "1"

# О котрій (за Києвом) надсилати ранкове нагадування про пост на сьогодні
REMIND_HOUR = int(os.getenv("REMIND_HOUR", "9"))
