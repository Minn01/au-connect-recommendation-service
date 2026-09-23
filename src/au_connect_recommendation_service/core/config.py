import os
from dotenv import load_dotenv

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")
MONGODB_DB = os.getenv("MONGODB_DB", "au_connect")

if not MONGODB_URL:
    raise RuntimeError("MONGODB_URL is not configured")