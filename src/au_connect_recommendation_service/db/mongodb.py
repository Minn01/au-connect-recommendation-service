from pymongo import AsyncMongoClient

from au_connect_recommendation_service.core.config import MONGODB_DB, MONGODB_URI

db_client = AsyncMongoClient(MONGODB_URI)
db = db_client[MONGODB_DB]
