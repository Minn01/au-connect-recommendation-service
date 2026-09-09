from bson import ObjectId

from au_connect_recommendation_service.db.mongodb import db
from au_connect_recommendation_service.models.user import User, map_user
from au_connect_recommendation_service.services.similarity import (
    calculate_profile_similarity,
)


async def get_connection_recommendations(
    user_id: str,
    limit: int = 10,
):
    if limit <= 0:
        return []

    # Find current user
    current_user = await get_current_user(user_id)
    if current_user is None:
        return []

    # Remove existing connections and pending requests from recommendations.
    connected_user_ids = await get_connected_users(user_id)
    pending_requests_user_ids = await get_pending_request_users(user_id)
    excluded_user_ids = connected_user_ids | pending_requests_user_ids

    candidates = await get_candidate_users(
        curr_user_id=user_id,
        excluded_user_ids=excluded_user_ids,
    )

    # Reuse the connection IDs already fetched for candidate exclusion.
    mutual_counts = await calculate_mutual_connections(
        candidate_users=candidates,
        current_user_connection_ids=connected_user_ids,
    )

    recommendations = []
    max_mutual = max(mutual_counts.values(), default=0)
    for candidate in candidates:
        profile_score = await calculate_profile_similarity(
            current_user=current_user,
            candidate=candidate,
        )
        mutual_count = mutual_counts[candidate.id]
        mutual_score = mutual_count / max_mutual if max_mutual else 0.0

        final_score = mutual_score * 0.60 + profile_score * 0.40
        recommendations.append(
            {
                "user": candidate,
                "score": final_score,
            }
        )

    recommendations.sort(key=lambda recommendation: recommendation["score"], reverse=True)
    return recommendations[:limit]


async def get_current_user(user_id: str) -> User | None:
    user_docs = db["User"]

    current_user = await user_docs.find_one({"_id": ObjectId(user_id)})

    if current_user is None:
        return None

    return map_user(current_user)


async def get_connected_users(user_id: str) -> set[str]:
    connection_docs = db["Connection"]
    current_user_id = ObjectId(user_id)

    connections = await connection_docs.find(
        {
            "$or": [
                {"userAId": current_user_id},
                {"userBId": current_user_id},
            ]
        }
    ).to_list(length=None)

    connected_ids = set()
    for con in connections:
        if con["userAId"] == current_user_id:
            connected_ids.add(str(con["userBId"]))
        else:
            connected_ids.add(str(con["userAId"]))

    return connected_ids


async def get_candidate_users(
    curr_user_id: str,
    excluded_user_ids: set[str],
    limit: int = 100,
):
    user_docs = db["User"]

    excluded_ids = [ObjectId(curr_user_id)]
    excluded_ids.extend(ObjectId(user_id) for user_id in excluded_user_ids)

    candidates = (
        await user_docs.find(
            {
                "_id": {"$nin": excluded_ids},
                "accountStatus": "ACTIVE",
            }
        )
        .limit(limit)
        .to_list(length=limit)
    )

    return [map_user(user) for user in candidates]


async def get_pending_request_users(user_id: str) -> set[str]:
    request_docs = db["ConnectionRequest"]
    current_user_id = ObjectId(user_id)

    requests = await request_docs.find(
        {
            "$or": [
                {"fromUserId": current_user_id},
                {"toUserId": current_user_id},
            ],
            "status": "PENDING",
        }
    ).to_list(length=None)

    pending_user_ids = set()

    for request in requests:
        if request["fromUserId"] == current_user_id:
            pending_user_ids.add(str(request["toUserId"]))
        else:
            pending_user_ids.add(str(request["fromUserId"]))

    return pending_user_ids


async def calculate_mutual_connections(
    candidate_users: list[User],
    current_user_connection_ids: set[str],
) -> dict[str, int]:
    mutual_connection_ids = {candidate.id: set() for candidate in candidate_users}

    if not candidate_users or not current_user_connection_ids:
        return {candidate_id: 0 for candidate_id in mutual_connection_ids}

    candidate_ids = {
        ObjectId(candidate.id): candidate.id for candidate in candidate_users
    }
    current_connection_ids = {
        ObjectId(connection_id) for connection_id in current_user_connection_ids
    }
    connection_docs = db["Connection"]

    connections = await connection_docs.find(
        {
            "$or": [
                {"userAId": {"$in": list(candidate_ids)}},
                {"userBId": {"$in": list(candidate_ids)}},
            ]
        }
    ).to_list(length=None)

    for connection in connections:
        user_a_id = connection["userAId"]
        user_b_id = connection["userBId"]

        if user_a_id in candidate_ids:
            candidate_id = candidate_ids[user_a_id]
            other_user_id = user_b_id
        elif user_b_id in candidate_ids:
            candidate_id = candidate_ids[user_b_id]
            other_user_id = user_a_id
        else:
            continue

        if other_user_id in current_connection_ids:
            mutual_connection_ids[candidate_id].add(other_user_id)

    return {
        candidate_id: len(connection_ids)
        for candidate_id, connection_ids in mutual_connection_ids.items()
    }
