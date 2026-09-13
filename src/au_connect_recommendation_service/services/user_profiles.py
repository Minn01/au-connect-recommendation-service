import asyncio
from collections.abc import Mapping
from typing import Any

from bson import ObjectId

from au_connect_recommendation_service.models.education import map_education
from au_connect_recommendation_service.models.experience import map_experience
from au_connect_recommendation_service.models.user import User, map_user


async def load_profile_relations(
    users: list[User],
    database: Mapping[str, Any],
) -> None:
    """Load Experience and Education documents for all users in two queries."""
    if not users:
        return

    users_by_id = {ObjectId(user.id): user for user in users}
    user_ids = list(users_by_id)

    experience_docs, education_docs = await asyncio.gather(
        database["Experience"]
        .find({"userId": {"$in": user_ids}})
        .to_list(length=None),
        database["Education"]
        .find({"userId": {"$in": user_ids}})
        .to_list(length=None),
    )

    for user in users:
        user.experience = []
        user.education = []

    for doc in experience_docs:
        user = users_by_id.get(doc["userId"])
        if user is not None:
            user.experience.append(map_experience(doc))

    for doc in education_docs:
        user = users_by_id.get(doc["userId"])
        if user is not None:
            user.education.append(map_education(doc))


async def load_user_profile(
    user_id: ObjectId,
    database: Mapping[str, Any],
) -> User | None:
    user_doc = await database["User"].find_one({"_id": user_id})
    if user_doc is None:
        return None

    user = map_user(user_doc)
    await load_profile_relations([user], database)
    return user
