from pymongo import AsyncMongoClient

from au_connect_recommendation_service.core.config import MONGODB_DB, MONGODB_URL

db_client = AsyncMongoClient(MONGODB_URL)
db = db_client[MONGODB_DB]
