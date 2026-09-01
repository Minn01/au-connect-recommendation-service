import os

from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB = os.getenv("MONGODB_DB", "au_connect")

if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI is not configured")