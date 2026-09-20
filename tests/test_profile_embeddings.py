import os
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017")

from bson import ObjectId

from au_connect_recommendation_service.enums.account_status import AccountStatus
from au_connect_recommendation_service.models.education import Education
from au_connect_recommendation_service.models.experience import Experience
from au_connect_recommendation_service.models.user import User
from au_connect_recommendation_service.services import profile_embeddings


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    async def to_list(self, length=None):
        return self.documents if length is None else self.documents[:length]


class FakeEmbeddingCollection:
    def __init__(self, documents=()):
        self.documents = {document["userId"]: deepcopy(document) for document in documents}
        self.find_queries = []
        self.bulk_calls = []
        self.index_calls = []

    def find(self, query):
        self.find_queries.append(query)
        user_ids = set(query["userId"]["$in"])
        return FakeCursor([
            deepcopy(document)
            for user_id, document in self.documents.items()
            if user_id in user_ids
        ])

    async def bulk_write(self, operations, ordered):
        self.bulk_calls.append((operations, ordered))
        for operation in operations:
            self.documents[operation._filter["userId"]] = deepcopy(
                operation._doc["$set"]
            )

    async def create_index(self, keys, **kwargs):
        self.index_calls.append((keys, kwargs))
        return kwargs["name"]

    async def delete_one(self, query):
        deleted = self.documents.pop(query["userId"], None) is not None
        return SimpleNamespace(deleted_count=int(deleted))


class PagedCursor(FakeCursor):
    def sort(self, *_args):
        return self

    def limit(self, _limit):
        return self


class PagedUserCollection:
    def __init__(self, pages):
        self.pages = list(pages)
        self.queries = []

    def find(self, query):
        self.queries.append(query)
        return PagedCursor(self.pages.pop(0))


def make_user(user_id=None, *, title="Developer", about="Builds services"):
    user_id = user_id or ObjectId()
    return User(
        id=str(user_id),
        username=str(user_id),
        title=title,
        location="Bangkok",
        about=about,
        account_status=AccountStatus.ACTIVE,
        experience=[
            Experience(
                "experience",
                "Backend Engineer",
                "FULL_TIME",
                "AU Connect",
                1,
                2025,
                None,
                None,
                True,
                str(user_id),
            )
        ],
        education=[
            Education(
                "education",
                "Assumption University",
                "BSc",
                "Computer Science",
                8,
                2022,
                5,
                2026,
                str(user_id),
            )
        ],
    )


def fake_vectors(texts):
    return {text: [1.0, float(index)] for index, text in enumerate(sorted(texts))}


class ProfileEmbeddingPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def test_source_hash_is_normalized_deterministic_and_embedding_only(self):
        first = make_user(title=" Developer ", about=" BUILDS SERVICES ")
        first.experience.append(
            Experience(
                "second",
                "Data Engineer",
                "FREELANCE",
                "Different Company",
                2,
                2024,
                None,
                None,
                False,
                first.id,
            )
        )
        second = make_user(title="developer", about="builds services")
        second.experience.insert(
            0,
            Experience(
                "second",
                " data engineer ",
                "PART_TIME",
                "Another Company",
                3,
                2023,
                None,
                None,
                False,
                second.id,
            ),
        )
        second.location = "A different location"
        second.experience[0].company = "Another Company"
        second.education[0].degree = "MSc"
        second.education[0].school = "Another School"

        first_sources = profile_embeddings.embedding_sources(first)
        second_sources = profile_embeddings.embedding_sources(second)
        self.assertEqual(first_sources, second_sources)
        self.assertEqual(
            profile_embeddings.embedding_source_hash(first_sources),
            profile_embeddings.embedding_source_hash(second_sources),
        )

        second.about = "Changed relevant text"
        self.assertNotEqual(
            profile_embeddings.embedding_source_hash(first_sources),
            profile_embeddings.embedding_source_hash(
                profile_embeddings.embedding_sources(second)
            ),
        )

    async def test_reuses_saved_embeddings_when_hash_and_model_match(self):
        user = make_user()
        sources = profile_embeddings.embedding_sources(user)
        saved = profile_embeddings.build_embedding_document(
            user,
            sources,
            fake_vectors(sources.all_texts()),
        )
        collection = FakeEmbeddingCollection([saved])

        with (
            patch.object(profile_embeddings, "db", {"UserEmbedding": collection}),
            patch.object(
                profile_embeddings,
                "encode_normalized_texts",
                new=AsyncMock(),
            ) as encode,
        ):
            result = await profile_embeddings.ensure_profile_embeddings([user])

        encode.assert_not_awaited()
        self.assertEqual(result.regenerated_user_ids, frozenset())
        self.assertEqual(set(result.embeddings), set(sources.all_texts()))
        self.assertEqual(collection.bulk_calls, [])

    async def test_changed_profile_text_regenerates_and_upserts(self):
        user_id = ObjectId()
        old_user = make_user(user_id, title="Old title")
        old_sources = profile_embeddings.embedding_sources(old_user)
        saved = profile_embeddings.build_embedding_document(
            old_user,
            old_sources,
            fake_vectors(old_sources.all_texts()),
        )
        current_user = make_user(user_id, title="New title")
        current_sources = profile_embeddings.embedding_sources(current_user)
        collection = FakeEmbeddingCollection([saved])

        with (
            patch.object(profile_embeddings, "db", {"UserEmbedding": collection}),
            patch.object(
                profile_embeddings,
                "encode_normalized_texts",
                new=AsyncMock(side_effect=fake_vectors),
            ) as encode,
        ):
            result = await profile_embeddings.ensure_profile_embeddings([current_user])

        encode.assert_awaited_once()
        self.assertEqual(result.regenerated_user_ids, frozenset({str(user_id)}))
        self.assertEqual(len(collection.bulk_calls), 1)
        stored = collection.documents[user_id]
        self.assertEqual(stored["embeddings"]["title"]["text"], "new title")
        self.assertEqual(
            set(stored["embeddings"]),
            {
                "title",
                "about",
                "experienceTitles",
                "educationFieldsOfStudy",
            },
        )
        self.assertNotIn("location", stored["embeddings"])
        self.assertNotIn("degree", stored["embeddings"])
        self.assertNotIn("school", stored["embeddings"])
        self.assertEqual(
            stored["sourceHash"],
            profile_embeddings.embedding_source_hash(current_sources),
        )

    async def test_model_change_makes_saved_embedding_stale(self):
        user = make_user()
        sources = profile_embeddings.embedding_sources(user)
        saved = profile_embeddings.build_embedding_document(
            user,
            sources,
            fake_vectors(sources.all_texts()),
        )
        saved["model"]["version"] = "previous-version"
        collection = FakeEmbeddingCollection([saved])

        with (
            patch.object(profile_embeddings, "db", {"UserEmbedding": collection}),
            patch.object(
                profile_embeddings,
                "encode_normalized_texts",
                new=AsyncMock(side_effect=fake_vectors),
            ) as encode,
        ):
            result = await profile_embeddings.ensure_profile_embeddings([user])

        encode.assert_awaited_once()
        self.assertEqual(result.regenerated_user_ids, frozenset({user.id}))
        self.assertEqual(
            collection.documents[ObjectId(user.id)]["model"],
            {
                "name": profile_embeddings.EMBEDDING_MODEL_NAME,
                "version": profile_embeddings.EMBEDDING_MODEL_VERSION,
            },
        )

    async def test_batch_loads_and_generates_multiple_users_once(self):
        users = [make_user(), make_user(title="Designer", about="Designs products")]
        collection = FakeEmbeddingCollection()

        with (
            patch.object(profile_embeddings, "db", {"UserEmbedding": collection}),
            patch.object(
                profile_embeddings,
                "encode_normalized_texts",
                new=AsyncMock(side_effect=fake_vectors),
            ) as encode,
        ):
            result = await profile_embeddings.ensure_profile_embeddings(users)

        encode.assert_awaited_once()
        self.assertEqual(len(collection.find_queries), 1)
        self.assertEqual(
            set(collection.find_queries[0]["userId"]["$in"]),
            {ObjectId(user.id) for user in users},
        )
        self.assertEqual(len(collection.bulk_calls[0][0]), 2)
        self.assertEqual(result.regenerated_user_ids, frozenset(user.id for user in users))

    async def test_empty_optional_fields_are_saved_and_then_reused(self):
        user = make_user(title=None, about=None)
        user.experience = []
        user.education = []
        collection = FakeEmbeddingCollection()

        with (
            patch.object(profile_embeddings, "db", {"UserEmbedding": collection}),
            patch.object(
                profile_embeddings,
                "encode_normalized_texts",
                new=AsyncMock(),
            ) as encode,
        ):
            first = await profile_embeddings.ensure_profile_embeddings([user])
            second = await profile_embeddings.ensure_profile_embeddings([user])

        encode.assert_not_awaited()
        self.assertEqual(first.regenerated_user_ids, frozenset({user.id}))
        self.assertEqual(second.regenerated_user_ids, frozenset())
        document = collection.documents[ObjectId(user.id)]
        self.assertIsNone(document["embeddings"]["title"])
        self.assertIsNone(document["embeddings"]["about"])
        self.assertEqual(document["embeddings"]["experienceTitles"], [])
        self.assertEqual(document["embeddings"]["educationFieldsOfStudy"], [])

    async def test_embedding_failure_is_propagated_without_upsert(self):
        user = make_user()
        collection = FakeEmbeddingCollection()

        with (
            patch.object(profile_embeddings, "db", {"UserEmbedding": collection}),
            patch.object(
                profile_embeddings,
                "encode_normalized_texts",
                new=AsyncMock(side_effect=RuntimeError("inference failed")),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                await profile_embeddings.ensure_profile_embeddings([user])

        self.assertEqual(collection.bulk_calls, [])

    async def test_creates_unique_user_id_index(self):
        collection = FakeEmbeddingCollection()
        with patch.object(profile_embeddings, "db", {"UserEmbedding": collection}):
            index_name = await profile_embeddings.ensure_user_embedding_index()

        self.assertEqual(index_name, profile_embeddings.USER_ID_INDEX_NAME)
        self.assertEqual(
            collection.index_calls,
            [
                (
                    [("userId", 1)],
                    {
                        "unique": True,
                        "name": profile_embeddings.USER_ID_INDEX_NAME,
                    },
                )
            ],
        )

    async def test_delete_user_embedding(self):
        user = make_user()
        sources = profile_embeddings.embedding_sources(user)
        saved = profile_embeddings.build_embedding_document(
            user,
            sources,
            fake_vectors(sources.all_texts()),
        )
        collection = FakeEmbeddingCollection([saved])
        with patch.object(profile_embeddings, "db", {"UserEmbedding": collection}):
            self.assertTrue(await profile_embeddings.delete_user_embedding(user.id))
            self.assertFalse(await profile_embeddings.delete_user_embedding(user.id))

    async def test_refresh_reports_missing_profile(self):
        user_id = str(ObjectId())
        with (
            patch.object(
                profile_embeddings,
                "load_user_profile",
                new=AsyncMock(return_value=None),
            ),
            self.assertRaises(profile_embeddings.UserProfileNotFoundError),
        ):
            await profile_embeddings.refresh_user_embedding(user_id)


class BackfillTests(unittest.IsolatedAsyncioTestCase):
    async def test_backfill_processes_active_users_in_batches(self):
        object_ids = [ObjectId() for _ in range(5)]
        documents = [
            {
                "_id": object_id,
                "username": str(object_id),
                "title": None,
                "location": None,
                "about": None,
                "accountStatus": "ACTIVE",
            }
            for object_id in object_ids
        ]
        users = PagedUserCollection([
            documents[:2],
            documents[2:4],
            documents[4:],
            [],
        ])

        async def ensure(batch):
            return profile_embeddings.EmbeddingBatchResult(
                embeddings={},
                regenerated_user_ids=frozenset(user.id for user in batch),
            )

        with (
            patch.object(profile_embeddings, "db", {"User": users}),
            patch.object(
                profile_embeddings,
                "load_profile_relations",
                new=AsyncMock(),
            ) as load_relations,
            patch.object(
                profile_embeddings,
                "ensure_profile_embeddings",
                new=AsyncMock(side_effect=ensure),
            ) as ensure_embeddings,
        ):
            result = await profile_embeddings.backfill_active_user_embeddings(
                batch_size=2
            )

        self.assertEqual(result, profile_embeddings.BackfillResult(5, 5))
        self.assertEqual(load_relations.await_count, 3)
        self.assertEqual(ensure_embeddings.await_count, 3)
        self.assertEqual(
            [len(call.args[0]) for call in ensure_embeddings.await_args_list],
            [2, 2, 1],
        )
        self.assertEqual(users.queries[0], {"accountStatus": "ACTIVE"})
        self.assertEqual(
            users.queries[1],
            {"accountStatus": "ACTIVE", "_id": {"$gt": object_ids[1]}},
        )


if __name__ == "__main__":
    unittest.main()
