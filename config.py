import os

BOT_TOKEN = os.getenv("8559551039:AAHIXaeGLeVMRCZBg0n8wDIqyNsgTCpQyFM")
ADMINS = [int(x) for x in os.getenv("ADMINS", "409873627").split(",") if x]
DB_PATH = "secret_santa.db"
REVEAL_DATE = "19 декабря"
