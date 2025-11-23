import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",") if x]
DB_PATH = "secret_santa.db"
REVEAL_DATE = "1 декабря"

