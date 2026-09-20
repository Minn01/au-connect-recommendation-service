import os
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB", "au_connect")
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")

from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from au_connect_recommendation_service.core.env import INTERNAL_API_KEY
from au_connect_recommendation_service.core.recommendation_cursor import encode_cursor
from au_connect_recommendation_service.routes.connections import router
from au_connect_recommendation_service.services import connection_recommender as service
from test_connection_recommender import make_user, FakeCollection


class PaginationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.current = make_user(ObjectId())
        self.candidates = [make_user(ObjectId(f"{i:024x}")) for i in range(1, 106)]
        mocks = {
            "get_current_user": self.current,
            "get_connected_users": set(),
            "get_pending_request_users": set(),
            "get_candidate_users": list(reversed(self.candidates)),
            "load_profile_relations": None,
            "prepare_profile_embeddings": {},
            "calculate_mutual_connections": {u.id: 0 for u in self.candidates},
            "calculate_profile_similarity": 0.5,
        }
        self.mocks = {name: self.stack.enter_context(patch.object(service, name, new=AsyncMock(return_value=value))) for name, value in mocks.items()}
        app = FastAPI()
        app.include_router(router)
        self.client = self.stack.enter_context(TestClient(app))
        self.path = f"/recommendations/connections/{self.current.id}"
        self.headers = {"x-internal-service-key": INTERNAL_API_KEY}

    def get(self, **params):
        return self.client.get(self.path, params=params, headers=self.headers)

    def test_boundaries_contract_and_continuation_with_equal_scores(self):
        for size in (0, 9, 10, 11, 20, 105):
            with self.subTest(size=size):
                self.mocks["get_candidate_users"].return_value = list(reversed(self.candidates[:size]))
                seen = []
                params = {"limit": 10}
                while True:
                    response = self.get(**params)
                    self.assertEqual(response.status_code, 200, response.text)
                    body = response.json()
                    self.assertIs(body["success"], True)
                    self.assertIsNone(body["error"])
                    data = body["data"]
                    self.assertEqual(set(data), {"recommendations", "nextCursor", "hasMore"})
                    self.assertIs(type(data["hasMore"]), bool)
                    self.assertLessEqual(len(data["recommendations"]), 10)
                    for item in data["recommendations"]:
                        self.assertTrue(ObjectId.is_valid(item["user"]["id"]))
                        self.assertEqual(item["score"], 0.2)
                        seen.append(item["user"]["id"])
                    if not data["hasMore"]:
                        self.assertIsNone(data["nextCursor"])
                        break
                    self.assertIsInstance(data["nextCursor"], str)
                    self.assertTrue(data["nextCursor"])
                    params["cursor"] = data["nextCursor"]
                self.assertEqual(seen, [u.id for u in self.candidates[:size]])

    def test_invalid_tampered_wrong_user_and_invalid_payload_cursors(self):
        valid = self.get(limit=10).json()["data"]["nextCursor"]
        tokens = ["", "garbage", valid[:-5] + "aaaaa", encode_cursor(str(ObjectId()), 0.2, self.candidates[0].id), encode_cursor(self.current.id, float("nan"), self.candidates[0].id)]
        for token in tokens:
            with self.subTest(token=token):
                response = self.get(cursor=token)
                self.assertEqual(response.status_code, 400)
                self.assertIn("cursor", response.json()["detail"])

    def test_limits_default_and_validation(self):
        self.assertEqual(len(self.get().json()["data"]["recommendations"]), 10)
        for limit in (1, 50):
            self.assertEqual(len(self.get(limit=limit).json()["data"]["recommendations"]), limit)
        for limit in (0, -1, 51, "abc", "1.5"):
            self.assertEqual(self.get(limit=limit).status_code, 422)
        self.assertEqual(self.client.get('/recommendations/connections/invalid', headers=self.headers).status_code, 422)

    def test_authentication(self):
        self.assertEqual(self.client.get(self.path).status_code, 401)
        self.assertEqual(self.client.get(self.path, headers={"x-internal-service-key": "wrong"}).status_code, 403)
        self.mocks["get_current_user"].assert_not_awaited()

    def test_missing_user_and_disappearing_candidates(self):
        token = self.get(limit=10).json()["data"]["nextCursor"]
        self.mocks["get_candidate_users"].return_value = []
        self.assertEqual(self.get(cursor=token).json()["data"], {"recommendations": [], "nextCursor": None, "hasMore": False})
        self.mocks["get_current_user"].return_value = None
        self.assertEqual(self.get().json()["data"]["recommendations"], [])


class EligibilityQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_candidates_exclude_self_connections_and_pending_without_cutoff(self):
        current, connected, pending = ObjectId(), ObjectId(), ObjectId()
        users = FakeCollection([])
        with patch.object(service, "db", {"User": users}):
            await service.get_candidate_users(str(current), {str(connected), str(pending)})
        query = users.queries[0]
        self.assertEqual(query["accountStatus"], "ACTIVE")
        self.assertEqual(set(query["_id"]["$nin"]), {current, connected, pending})

    async def test_pending_requests_exclude_both_directions(self):
        current, incoming, outgoing = ObjectId(), ObjectId(), ObjectId()
        requests = FakeCollection([
            {"fromUserId": incoming, "toUserId": current},
            {"fromUserId": current, "toUserId": outgoing},
        ])
        with patch.object(service, "db", {"ConnectionRequest": requests}):
            self.assertEqual(await service.get_pending_request_users(str(current)), {str(incoming), str(outgoing)})
        self.assertEqual(requests.queries[0], {"$or": [{"fromUserId": current}, {"toUserId": current}], "status": "PENDING"})
