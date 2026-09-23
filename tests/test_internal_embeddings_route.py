import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB", "au-connect")
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")

from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException, status

from au_connect_recommendation_service.routes import internal_embeddings


class FakeUserCollection:
    def __init__(self, user):
        self.user = user
        self.calls = []

    async def find_one(self, query, projection):
        self.calls.append((query, projection))
        return self.user


class InternalEmbeddingRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_202_contract_and_schedules_background_refresh(self):
        user_id = str(ObjectId())
        users = FakeUserCollection({"_id": ObjectId(user_id)})
        tasks = BackgroundTasks()

        with (
            patch.object(internal_embeddings, "db", {"User": users}),
            patch.object(
                internal_embeddings,
                "refresh_user_embedding_background",
                new=AsyncMock(),
            ) as refresh,
        ):
            response = await internal_embeddings.schedule_user_embedding_refresh(
                user_id,
                tasks,
            )

        self.assertEqual(response, {"status": "accepted", "userId": user_id})
        self.assertEqual(len(tasks.tasks), 1)
        self.assertIs(tasks.tasks[0].func, refresh)
        refresh.assert_not_awaited()
        endpoint_route = next(
            route
            for route in internal_embeddings.router.routes
            if route.path == "/internal/users/{user_id}/embedding"
        )
        self.assertEqual(endpoint_route.status_code, status.HTTP_202_ACCEPTED)

    async def test_rejects_invalid_user_id(self):
        with self.assertRaises(HTTPException) as raised:
            await internal_embeddings.schedule_user_embedding_refresh(
                "not-an-object-id",
                BackgroundTasks(),
            )
        self.assertEqual(raised.exception.status_code, 422)

    async def test_returns_404_for_missing_user(self):
        users = FakeUserCollection(None)
        with patch.object(internal_embeddings, "db", {"User": users}):
            with self.assertRaises(HTTPException) as raised:
                await internal_embeddings.schedule_user_embedding_refresh(
                    str(ObjectId()),
                    BackgroundTasks(),
                )
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
