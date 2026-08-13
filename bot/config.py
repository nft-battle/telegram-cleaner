import os

from dotenv import load_dotenv

load_dotenv()

API_ID: int = int(os.getenv("API_ID", "0") or 0)
API_HASH: str = os.getenv("API_HASH", "").strip()
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS: list[int] = [
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]
DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
PORT: int = int(os.getenv("PORT", "10000"))
DB_PATH: str = os.getenv("DB_PATH", "cleaner_data.db").strip()

PAGE_SIZE = 6