# AU Connect — Recommendation Service

The **AU Connect Recommendation Service** is a dedicated service responsible for helping users discover relevant content on the AU Connect platform.

## Purpose

As AU Connect grows, users will have more posts and content available to them. Simply displaying content in chronological order can make it harder for users to discover posts that are relevant or interesting to them.

The Recommendation Service is intended to address this by analyzing available information about users and content and producing **personalized content recommendations**.

Instead of requiring the main AU Connect application to handle recommendation logic itself, this functionality is separated into its own service.

## What It Does

The service is designed to:

- Recommend relevant posts and content to users
- Help users discover content they may be interested in
- Provide a more personalized experience on AU Connect
- Reduce the amount of recommendation-specific logic handled by the main application
- Allow the recommendation system to be improved independently as the platform develops

## How It Fits Into AU Connect

The Recommendation Service is one of several supporting services that make up the AU Connect platform.

```text
                         AU Connect
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
    Main Application   Admin Application   Supporting Services
                                                 │
                              ┌──────────────────┴──────────────┐
                              │                                 │
                              ▼                                 ▼
                    Recommendation Service          Video Thumbnail Function
```

The main AU Connect application can request recommendations from this service and use the results to display personalized content to users.

## Why Have a Separate Service?

Recommendation systems can become increasingly complex as a platform grows. Keeping this functionality separate allows AU Connect to develop its recommendation capabilities without making the main application responsible for all of the associated processing and logic.

This separation also makes it possible to improve or replace the recommendation approach in the future without requiring major changes to the rest of the AU Connect platform.

## Future Development

The Recommendation Service is intended to evolve alongside AU Connect.

Future improvements may include:

- More personalized recommendations
- Better understanding of user interests
- Improved content ranking
- Using user interactions and engagement to improve recommendations
- More advanced recommendation algorithms
- Additional recommendation types

The technical implementation and recommendation approach may change as the project develops.

---

**AU Connect — Recommendation Service**

Helping AU Connect users discover content that is relevant to them.

## Hybrid profile similarity

Profile similarity uses title (25%), about (25%), experience titles (25%),
education (15%), and location (10%). Education compares each pair of records
using field of study (60%), degree (20%), and school (20%), then averages the
best matches in both directions. Experience titles use the same list matching.
Company names are not compared. Text and record duplicates are removed after
trimming and case folding. Degree aliases are intentionally limited to explicit
variants in `DEGREE_ALIASES`; unknown degrees use normalized exact matching.

Profile embeddings are stored in MongoDB's `UserEmbedding` collection. A
recommendation request loads all required documents in one query, reuses documents
whose model identity and profile source hash still match, and batch-encodes only
missing or stale users. Model inference runs in a worker thread. Normalized vectors
are reused for dot-product cosine scoring. Both sides use `query: ` per the
[E5 model guidance](https://huggingface.co/intfloat/multilingual-e5-small#faq).
Negative cosine scores are clipped to zero and scores are bounded by one.
There is no universal match threshold.

Missing components return `None`; a comparable mismatch returns zero. Weights
are redistributed only over available components (also within education pairs).
Entries with no comparable fields are omitted from list matching. With no
comparable information, the public async function returns `0.0`.
`profile_similarity_breakdown()` exposes component scores, effective weights,
available-weight coverage, and the final score for internal debugging only.
Coverage measures available top-level weights, not completeness within records.
Sparse profiles can score highly despite limited evidence; scores are not
probabilities.

Experience and education are loaded from their separate MongoDB collections in
two batch queries for the current user and all candidates. The outer recommendation
score remains 60% mutual connections and 40% profile similarity.

The main app should request a refresh after saving a user's title, about,
experience, or education:

```http
PUT /internal/users/{user_id}/embedding
x-internal-service-key: <INTERNAL_API_KEY>
```

The endpoint validates that the user exists and returns `202 Accepted` after
scheduling a background refresh. Repeated refreshes are idempotent when the
normalized profile hash and embedding model identity are unchanged. Profile
updates are eventually consistent while the background task runs.

Backfill existing active users in bounded batches:

```bash
uv run python scripts/backfill_user_embeddings.py --batch-size 100
```

The service creates a unique index on `UserEmbedding.userId` at startup. The
authoritative Prisma schema in the main app should also define `@@index([userId])`
on `Experience` and `Education`; `schema.txt` in this repository is only a schema
reference and is not modified by this service.

Run the fast mocked tests separately from model inference:

```bash
uv run python -m unittest discover -s tests -p 'test_similarity.py' -v
uv run python -m unittest discover -s tests -p 'test_connection_recommender.py' -v
```

Run the real-model profile example and print both component breakdowns:

```bash
uv run python -m unittest discover -s tests/integration -v
```

The example asserts only that a software profile ranks above a culinary profile,
not exact scores. It uses the existing model cache (or downloads the model if
needed). The existing `tests/test_embedding_model.py` is another real-model test;
plain discovery of the entire `tests` directory includes that test.
