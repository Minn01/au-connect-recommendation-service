import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")

from bson import ObjectId

from au_connect_recommendation_service.enums.account_status import AccountStatus
from au_connect_recommendation_service.models.user import User
from au_connect_recommendation_service.services import connection_recommender


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    async def to_list(self, length=None):
        return self.documents if length is None else self.documents[:length]


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents
        self.queries = []

    def find(self, query):
        self.queries.append(query)
        return FakeCursor(self.documents)


def make_user(user_id: ObjectId) -> User:
    return User(
        id=str(user_id),
        username=str(user_id),
        title=None,
        location=None,
        about=None,
        account_status=AccountStatus.ACTIVE,
        experience=[],
        education=[],
    )


class MutualConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_mutual_connections_in_both_storage_directions(self):
        candidate_one = ObjectId()
        candidate_two = ObjectId()
        mutual_one = ObjectId()
        mutual_two = ObjectId()
        not_mutual = ObjectId()
        connections = FakeCollection(
            [
                {"userAId": mutual_one, "userBId": candidate_one},
                {"userAId": candidate_one, "userBId": mutual_two},
                {"userAId": candidate_two, "userBId": mutual_one},
                {"userAId": candidate_two, "userBId": not_mutual},
            ]
        )

        with patch.object(connection_recommender, "db", {"Connection": connections}):
            counts = await connection_recommender.calculate_mutual_connections(
                candidate_users=[make_user(candidate_one), make_user(candidate_two)],
                current_user_connection_ids={str(mutual_one), str(mutual_two)},
            )

        self.assertEqual(counts, {str(candidate_one): 2, str(candidate_two): 1})
        self.assertEqual(len(connections.queries), 1)
        batch_query = connections.queries[0]["$or"]
        self.assertEqual([set(query) for query in batch_query], [{"userAId"}, {"userBId"}])
        self.assertTrue(all("$in" in next(iter(query.values())) for query in batch_query))

    async def test_returns_zero_counts_without_mutual_connections_or_candidates(self):
        candidate = ObjectId()
        connections = FakeCollection([])

        with patch.object(connection_recommender, "db", {"Connection": connections}):
            no_mutual_counts = await connection_recommender.calculate_mutual_connections(
                candidate_users=[make_user(candidate)],
                current_user_connection_ids=set(),
            )
            no_candidate_counts = await connection_recommender.calculate_mutual_connections(
                candidate_users=[],
                current_user_connection_ids={str(ObjectId())},
            )

        self.assertEqual(no_mutual_counts, {str(candidate): 0})
        self.assertEqual(no_candidate_counts, {})
        self.assertEqual(connections.queries, [])


class RecommendationPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_excludes_connected_and_pending_users_and_respects_limit(self):
        current = make_user(ObjectId())
        connected_user_id = str(ObjectId())
        pending_user_id = str(ObjectId())
        candidates = [make_user(ObjectId()), make_user(ObjectId()), make_user(ObjectId())]
        profile_scores = {
            candidates[0].id: 0.1,
            candidates[1].id: 0.8,
            candidates[2].id: 0.3,
        }

        with (
            patch.object(
                connection_recommender,
                "get_current_user",
                new=AsyncMock(return_value=current),
            ),
            patch.object(
                connection_recommender,
                "get_connected_users",
                new=AsyncMock(return_value={connected_user_id}),
            ) as get_connected_users,
            patch.object(
                connection_recommender,
                "get_pending_request_users",
                new=AsyncMock(return_value={pending_user_id}),
            ),
            patch.object(
                connection_recommender,
                "get_candidate_users",
                new=AsyncMock(return_value=candidates),
            ) as get_candidate_users,
            patch.object(
                connection_recommender,
                "calculate_mutual_connections",
                new=AsyncMock(
                    return_value={
                        candidates[0].id: 1,
                        candidates[1].id: 2,
                        candidates[2].id: 0,
                    }
                ),
            ),
            patch.object(
                connection_recommender,
                "calculate_profile_similarity",
                new=AsyncMock(
                    side_effect=lambda current_user, candidate: profile_scores[candidate.id]
                ),
            ),
        ):
            recommendations = await connection_recommender.get_connection_recommendations(
                user_id=current.id,
                limit=2,
            )

        self.assertEqual(get_connected_users.await_count, 1)
        self.assertEqual(
            get_candidate_users.await_args.kwargs["excluded_user_ids"],
            {connected_user_id, pending_user_id},
        )
        self.assertEqual([item["user"].id for item in recommendations], [candidates[1].id, candidates[0].id])
        self.assertEqual(len(recommendations), 2)


if __name__ == "__main__":
    unittest.main()
