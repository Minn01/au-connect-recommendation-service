"""Read-only diagnostics for the connection-recommendation candidate query."""

import asyncio
from pprint import pformat

from bson import ObjectId

from au_connect_recommendation_service.core.config import MONGODB_DB, MONGODB_URL
from au_connect_recommendation_service.db.mongodb import db, db_client


TARGET_USER_ID = "6929aa8767c252bdb59d218f"


def mongodb_hostnames(uri: str) -> str:
    """Return URI hostnames without credentials, ports, paths, or query values."""
    authority = uri.split("://", 1)[-1].split("/", 1)[0]
    hosts = authority.rsplit("@", 1)[-1]
    hostnames = []
    for host in hosts.split(","):
        if host.startswith("["):
            hostname = host[1:].split("]", 1)[0]
        else:
            hostname = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        hostnames.append(hostname)
    return ", ".join(hostnames)


def typed(value: object) -> str:
    return f"{value} ({type(value).__name__})"


async def bson_type_counts(collection_name: str, field_name: str) -> list[dict]:
    pipeline = [
        {"$group": {"_id": {"$type": f"${field_name}"}, "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    cursor = await db[collection_name].aggregate(pipeline)
    return await cursor.to_list(length=None)


async def main() -> None:
    target_id = ObjectId(TARGET_USER_ID)

    try:
        users = db["User"]
        connections = db["Connection"]
        requests = db["ConnectionRequest"]

        target_user = await users.find_one(
            {"_id": target_id},
            {"username": 1, "accountStatus": 1},
        )
        string_id_user = await users.find_one(
            {"_id": TARGET_USER_ID},
            {"username": 1, "accountStatus": 1},
        )

        connection_query = {
            "$or": [
                {"userAId": target_id},
                {"userBId": target_id},
            ]
        }
        connection_docs = await connections.find(connection_query).to_list(length=None)
        connected_user_ids: set[str] = set()
        for connection in connection_docs:
            if connection["userAId"] == target_id:
                connected_user_ids.add(str(connection["userBId"]))
            else:
                connected_user_ids.add(str(connection["userAId"]))

        pending_request_query = {
            "$or": [
                {"fromUserId": target_id},
                {"toUserId": target_id},
            ],
            "status": "PENDING",
        }
        pending_request_docs = await requests.find(pending_request_query).to_list(
            length=None
        )
        pending_user_ids: set[str] = set()
        for request in pending_request_docs:
            if request["fromUserId"] == target_id:
                pending_user_ids.add(str(request["toUserId"]))
            else:
                pending_user_ids.add(str(request["fromUserId"]))

        excluded_user_ids = connected_user_ids | pending_user_ids
        excluded_ids = [target_id]
        excluded_ids.extend(ObjectId(user_id) for user_id in excluded_user_ids)
        candidate_query = {
            "_id": {"$nin": excluded_ids},
            "accountStatus": "ACTIVE",
        }
        candidate_docs = await users.find(
            candidate_query,
            {"username": 1, "accountStatus": 1},
        ).to_list(length=None)

        total_users, active_users, other_active_users = await asyncio.gather(
            users.count_documents({}),
            users.count_documents({"accountStatus": "ACTIVE"}),
            users.count_documents(
                {"_id": {"$ne": target_id}, "accountStatus": "ACTIVE"}
            ),
        )

        string_connection_count, string_pending_count = await asyncio.gather(
            connections.count_documents(
                {
                    "$or": [
                        {"userAId": TARGET_USER_ID},
                        {"userBId": TARGET_USER_ID},
                    ]
                }
            ),
            requests.count_documents(
                {
                    "$or": [
                        {"fromUserId": TARGET_USER_ID},
                        {"toUserId": TARGET_USER_ID},
                    ],
                    "status": "PENDING",
                }
            ),
        )

        print(f"1. MONGODB_DB: {MONGODB_DB}")
        print(f"2. MongoDB hostname(s): {mongodb_hostnames(MONGODB_URL)}")
        print(f"3. Target User exists with ObjectId _id: {target_user is not None}")
        if string_id_user is not None:
            print("   WARNING: target exists with a string _id but the service will not find it")
        print(
            "4. Target user: "
            + (
                f"username={target_user.get('username')!r}, "
                f"accountStatus={target_user.get('accountStatus')!r}"
                if target_user is not None
                else "<not found by the service query>"
            )
        )
        print(f"5. Total User count: {total_users}")
        print(f"6. ACTIVE User count: {active_users}")
        print(f"7. Other ACTIVE users excluding target: {other_active_users}")

        print(f"8. Existing Connection records involving target: {len(connection_docs)}")
        for connection in connection_docs:
            print(
                "   "
                f"_id={typed(connection.get('_id'))}, "
                f"userAId={typed(connection.get('userAId'))}, "
                f"userBId={typed(connection.get('userBId'))}"
            )
        if string_connection_count:
            print(
                "   WARNING: "
                f"{string_connection_count} additional record(s) use the target as a string"
            )
        print(f"9. IDs excluded by existing connections: {sorted(connected_user_ids)}")

        print(
            "10. PENDING ConnectionRequest records involving target: "
            f"{len(pending_request_docs)}"
        )
        for request in pending_request_docs:
            print(
                "   "
                f"_id={typed(request.get('_id'))}, "
                f"fromUserId={typed(request.get('fromUserId'))}, "
                f"toUserId={typed(request.get('toUserId'))}, "
                f"status={request.get('status')!r}"
            )
        if string_pending_count:
            print(
                "   WARNING: "
                f"{string_pending_count} additional PENDING record(s) use the target as a string"
            )
        print(f"11. IDs excluded by pending requests: {sorted(pending_user_ids)}")
        print(f"12. Final candidate query:\n{pformat(candidate_query, sort_dicts=False)}")
        print(f"13. Final candidate count: {len(candidate_docs)}")
        print("14. Candidate usernames + IDs:")
        for candidate in candidate_docs:
            print(
                f"   username={candidate.get('username')!r}, "
                f"_id={typed(candidate.get('_id'))}"
            )
        if not candidate_docs:
            print("   <none>")

        print("\nBSON field types across each collection:")
        type_fields = (
            ("User", "_id"),
            ("Connection", "userAId"),
            ("Connection", "userBId"),
            ("ConnectionRequest", "fromUserId"),
            ("ConnectionRequest", "toUserId"),
        )
        for collection_name, field_name in type_fields:
            counts = await bson_type_counts(collection_name, field_name)
            rendered = ", ".join(
                f"{entry['_id']}={entry['count']}" for entry in counts
            )
            print(f"- {collection_name}.{field_name}: {rendered or '<no documents>'}")
    finally:
        await db_client.close()


if __name__ == "__main__":
    asyncio.run(main())
