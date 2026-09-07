from bson import ObjectId

from au_connect_recommendation_service.models.user import User, map_user
from au_connect_recommendation_service.db.mongodb import db


async def get_connection_recommendations(
    user_id: str,
    limit: int = 10,
):
    # Find current user
    current_user = await get_current_user(user_id)
    if current_user is None:
        return []

    print(current_user.username)
    
    # 2. Find candidate users
    # 3. Remove existing connections
    # 4. Calculate mutual connections
    # 5. Calculate profile similarity
    # 6. Score
    # 7. Sort
    # 8. Return top N


    return {
        "user_id": current_user.id,
        "username": current_user.username,
    }

async def get_current_user(user_id: str) -> User | None:
    user_docs = db["User"]
    
    current_user = await user_docs.find_one(
        {"_id": ObjectId(user_id)}
    )

    if current_user is None:
        return None

    return map_user(current_user)
    

async def get_candidate_users():
    pass