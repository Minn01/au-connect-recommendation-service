import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, UpdateOne

from au_connect_recommendation_service.core.constants import (
    EMBEDDING_MODEL_NAME,
    EMBEDDING_MODEL_VERSION,
)
from au_connect_recommendation_service.db.mongodb import db
from au_connect_recommendation_service.models.user import User, map_user
from au_connect_recommendation_service.services.similarity import (
    Embeddings,
    encode_normalized_texts,
    normalize_text,
)
from au_connect_recommendation_service.services.user_profiles import (
    load_profile_relations,
    load_user_profile,
)

COLLECTION_NAME = "UserEmbedding"
USER_ID_INDEX_NAME = "unique_user_embedding_user_id"


class UserProfileNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class ProfileEmbeddingSources:
    title: str
    about: str
    experience_titles: tuple[str, ...]
    education_fields_of_study: tuple[str, ...]

    def all_texts(self) -> tuple[str, ...]:
        return tuple(
            text
            for text in (
                self.title,
                self.about,
                *self.experience_titles,
                *self.education_fields_of_study,
            )
            if text
        )


@dataclass(frozen=True)
class EmbeddingBatchResult:
    embeddings: dict[str, list[float]]
    regenerated_user_ids: frozenset[str]


@dataclass(frozen=True)
class BackfillResult:
    processed: int
    regenerated: int


def embedding_sources(user: User) -> ProfileEmbeddingSources:
    return ProfileEmbeddingSources(
        title=normalize_text(user.title),
        about=normalize_text(user.about),
        experience_titles=tuple(
            sorted(
                {
                    normalized
                    for entry in user.experience
                    if (normalized := normalize_text(entry.title))
                }
            )
        ),
        education_fields_of_study=tuple(
            sorted(
                {
                    normalized
                    for entry in user.education
                    if (normalized := normalize_text(entry.field_of_study))
                }
            )
        ),
    )


def embedding_source_hash(sources: ProfileEmbeddingSources) -> str:
    payload = {
        "about": sources.about,
        "educationFieldsOfStudy": list(sources.education_fields_of_study),
        "experienceTitles": list(sources.experience_titles),
        "title": sources.title,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _model_identity() -> dict[str, str]:
    return {
        "name": EMBEDDING_MODEL_NAME,
        "version": EMBEDDING_MODEL_VERSION,
    }


def _as_float_list(vector: Any) -> list[float]:
    return [float(value) for value in vector]


def _single_embedding(text: str, vectors: Embeddings) -> dict[str, Any] | None:
    if not text:
        return None
    return {"text": text, "vector": _as_float_list(vectors[text])}


def build_embedding_document(
    user: User,
    sources: ProfileEmbeddingSources,
    vectors: Embeddings,
    *,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "userId": ObjectId(user.id),
        "model": _model_identity(),
        "sourceHash": embedding_source_hash(sources),
        "embeddings": {
            "title": _single_embedding(sources.title, vectors),
            "about": _single_embedding(sources.about, vectors),
            "experienceTitles": [
                _single_embedding(text, vectors) for text in sources.experience_titles
            ],
            "educationFieldsOfStudy": [
                _single_embedding(text, vectors)
                for text in sources.education_fields_of_study
            ],
        },
        "updatedAt": updated_at or datetime.now(UTC),
    }


def _stored_embedding_map(document: dict[str, Any]) -> dict[str, list[float]] | None:
    embeddings = document.get("embeddings")
    if not isinstance(embeddings, dict):
        return None

    result: dict[str, list[float]] = {}
    entries = [embeddings.get("title"), embeddings.get("about")]
    list_field_names = ("experienceTitles", "educationFieldsOfStudy")
    for field_name in list_field_names:
        field_entries = embeddings.get(field_name)
        if not isinstance(field_entries, list):
            return None
        entries.extend(field_entries)

    for entry in entries:
        if entry is None:
            continue
        if not isinstance(entry, dict):
            return None
        text = entry.get("text")
        vector = entry.get("vector")
        if (
            not isinstance(text, str)
            or not text
            or not isinstance(vector, list)
            or not vector
        ):
            return None
        try:
            result[text] = [float(value) for value in vector]
        except (TypeError, ValueError):
            return None
    return result


def _reusable_embedding_map(
    document: dict[str, Any] | None,
    sources: ProfileEmbeddingSources,
) -> dict[str, list[float]] | None:
    if document is None:
        return None
    if document.get("model") != _model_identity():
        return None
    if document.get("sourceHash") != embedding_source_hash(sources):
        return None

    stored = _stored_embedding_map(document)
    if stored is None or set(stored) != set(sources.all_texts()):
        return None
    return stored


async def ensure_profile_embeddings(users: list[User]) -> EmbeddingBatchResult:
    """Batch-load saved vectors and generate only missing or stale user documents."""
    if not users:
        return EmbeddingBatchResult({}, frozenset())

    users_by_object_id = {ObjectId(user.id): user for user in users}
    saved_documents = (
        await db[COLLECTION_NAME]
        .find({"userId": {"$in": list(users_by_object_id)}})
        .to_list(length=None)
    )
    saved_by_user_id = {
        document["userId"]: document
        for document in saved_documents
        if document.get("userId") in users_by_object_id
    }

    sources_by_user_id = {
        object_id: embedding_sources(user)
        for object_id, user in users_by_object_id.items()
    }
    reusable_by_user_id: dict[ObjectId, dict[str, list[float]]] = {}
    stale_user_ids: list[ObjectId] = []
    for object_id, sources in sources_by_user_id.items():
        stored = _reusable_embedding_map(saved_by_user_id.get(object_id), sources)
        if stored is None:
            stale_user_ids.append(object_id)
        else:
            reusable_by_user_id[object_id] = stored

    generated_vectors: Embeddings = {}
    generated_documents: dict[ObjectId, dict[str, Any]] = {}
    if stale_user_ids:
        texts = {
            text
            for object_id in stale_user_ids
            for text in sources_by_user_id[object_id].all_texts()
        }
        if texts:
            generated_vectors = await encode_normalized_texts(texts)
        updated_at = datetime.now(UTC)
        generated_documents = {
            object_id: build_embedding_document(
                users_by_object_id[object_id],
                sources_by_user_id[object_id],
                generated_vectors,
                updated_at=updated_at,
            )
            for object_id in stale_user_ids
        }
        await db[COLLECTION_NAME].bulk_write(
            [
                UpdateOne(
                    {"userId": object_id},
                    {"$set": document},
                    upsert=True,
                )
                for object_id, document in generated_documents.items()
            ],
            ordered=False,
        )

    combined: dict[str, list[float]] = {}
    for vectors in reusable_by_user_id.values():
        combined.update(vectors)
    for document in generated_documents.values():
        stored = _stored_embedding_map(document)
        if stored is None:
            raise RuntimeError("Generated embedding document is invalid")
        combined.update(stored)

    return EmbeddingBatchResult(
        embeddings=combined,
        regenerated_user_ids=frozenset(str(object_id) for object_id in stale_user_ids),
    )


async def prepare_persistent_profile_embeddings(users: list[User]) -> Embeddings:
    return (await ensure_profile_embeddings(users)).embeddings


def parse_user_id(user_id: str) -> ObjectId:
    if not ObjectId.is_valid(user_id):
        raise ValueError("Invalid user ID")
    return ObjectId(user_id)


async def refresh_user_embedding(user_id: str) -> bool:
    object_id = parse_user_id(user_id)
    user = await load_user_profile(object_id, db)
    if user is None:
        raise UserProfileNotFoundError(user_id)

    result = await ensure_profile_embeddings([user])
    print("RESULT OF EMBEDDING: \n" + f"{result}")
    return user_id in result.regenerated_user_ids


async def delete_user_embedding(user_id: str) -> bool:
    result = await db[COLLECTION_NAME].delete_one({"userId": parse_user_id(user_id)})
    return result.deleted_count > 0


async def ensure_user_embedding_index() -> str:
    return await db[COLLECTION_NAME].create_index(
        [("userId", ASCENDING)],
        unique=True,
        name=USER_ID_INDEX_NAME,
    )


async def backfill_active_user_embeddings(batch_size: int = 100) -> BackfillResult:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    processed = 0
    regenerated = 0
    last_user_id: ObjectId | None = None

    while True:
        query: dict[str, Any] = {"accountStatus": "ACTIVE"}
        if last_user_id is not None:
            query["_id"] = {"$gt": last_user_id}

        user_documents = await (
            db["User"]
            .find(query)
            .sort("_id", ASCENDING)
            .limit(batch_size)
            .to_list(length=batch_size)
        )
        if not user_documents:
            break

        users = [map_user(document) for document in user_documents]
        await load_profile_relations(users, db)
        result = await ensure_profile_embeddings(users)
        processed += len(users)
        regenerated += len(result.regenerated_user_ids)
        last_user_id = user_documents[-1]["_id"]

    return BackfillResult(processed=processed, regenerated=regenerated)
