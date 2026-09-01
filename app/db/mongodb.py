from pymongo import MongoClient

from app.core.config import MONGODB_DB, MONGODB_URI

client = MongoClient(MONGODB_URI)
db = client[MONGODB_DB]