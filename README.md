# AU Connect Recommendation Service

This repository contains the recommendation service for **AU Connect**. It recommends users who may be useful or relevant connections based on profile similarity and mutual connections.

> This project is still under development. More features and documentation will be added later.

## Members

- Thant Zin Min
- Min Thant
- Si Thu Naung

## Current Features

- Recommends connection candidates for a user
- Excludes existing connections and pending requests
- Compares profile title, about, experience, education, and location
- Includes mutual connections in the ranking score
- Stores profile embeddings in MongoDB for reuse
- Refreshes embeddings when relevant profile information changes
- Loads users and related profile data in batches
- Supports backfilling embeddings for existing users

## Technologies

- Python
- FastAPI
- MongoDB
- Sentence Transformers
- `uv` for dependency and environment management

## Setup

Install the project dependencies:

```bash
uv sync
```

Add the required environment variables to your `.env` file:

```env
MONGODB_URL=your_mongodb_connection_string
MONGODB_DB=au_connect
INTERNAL_API_KEY=your_internal_service_key
```

Start the development server:

```bash
uv run fastapi dev src/au_connect_recommendation_service/main.py
```

The API documentation will be available at:

```text
http://127.0.0.1:8000/docs
```

## Main Endpoints

### Service Status

```http
GET /status
```

Checks whether the service, database, and embedding model are available.

### Connection Recommendations

`GET /recommendations/connections/{user_id}?limit=10&cursor=<token>`

Requires `x-internal-service-key`. `user_id` must be a 24-character MongoDB
ObjectId. `limit` defaults to 10 and accepts integers from 1 through 50. Omit
`cursor` for the first page; pass `data.nextCursor` unchanged for continuation.

```bash
curl --get 'http://127.0.0.1:8000/recommendations/connections/6929aa8767c252bdb59d218f' \
  --header 'x-internal-service-key: YOUR_INTERNAL_API_KEY' \
  --data-urlencode 'limit=10'

curl --get 'http://127.0.0.1:8000/recommendations/connections/6929aa8767c252bdb59d218f' \
  --header 'x-internal-service-key: YOUR_INTERNAL_API_KEY' \
  --data-urlencode 'limit=10' \
  --data-urlencode 'cursor=NEXT_CURSOR_FROM_PREVIOUS_RESPONSE'
```

Successful responses always include these fields:

```json
{
  "success": true,
  "data": {
    "recommendations": [
      {"user": {"id": "bbbbbbbbbbbbbbbbbbbbbbbb"}, "score": 0.82}
    ],
    "nextCursor": "opaque-next-page-token",
    "hasMore": true
  },
  "error": null
}
```

On the final page, `nextCursor` is explicitly `null` and `hasMore` is `false`.
The final page can contain results; no eligible candidates (or an unknown user)
returns an empty recommendations array with those same final-page fields.
Only IDs and scores are returned; the client hydrates profiles independently.

Candidates remain active users excluding self, existing connections, and pending
requests in either direction. Ranking remains 60% normalized mutual connections
and 40% profile similarity, descending by score with ascending user ID as the
tie-breaker. The previous arbitrary 100-candidate cutoff is removed.

Cursors are signed, versioned, user-scoped tokens recording the last score and
ID. They are opaque API values, not encrypted secrets. Each request recomputes
current ranking and returns candidates after that boundary. Unchanged data has
no duplicates or skips. Eligibility changes apply immediately; score changes
(including changes to mutual-count normalization) can move candidates across the
boundary, causing repeats or omissions during a traversal. Start without a cursor
to refresh the ranking. Cursors do not expire, but rotating `INTERNAL_API_KEY`
invalidates existing cursors. All replicas must use the same key; no new settings,
collections, or indexes are required.

Malformed, tampered, or wrong-user cursors return HTTP 400 JSON with `detail`.
Invalid limits, user IDs, or cursors longer than 1024 characters return HTTP 422
JSON. Missing/incorrect authentication remains HTTP 401/403.

Ranking uses batched database reads and existing persisted embeddings, with one
batched mutual-connection query when needed, as before. Every page scores all
eligible candidates; there is no per-candidate connection query. Run the embedding
backfill before serving existing users to reduce on-demand inference. The client's
3-second timeout needs validation with production-sized data: cold embeddings or
large candidate populations can exceed it. Local mocked tests establish correctness,
not production latency; larger deployments may require a separately designed stored
ranking strategy.

### Refresh User Embedding

```http
PUT /internal/users/{user_id}/embedding
```

Schedules a background refresh of a user's stored profile embeddings. This internal endpoint requires the `x-internal-service-key` header.

## Backfill Existing Users

Generate stored embeddings for existing active users:

```bash
uv run python scripts/backfill_user_embeddings.py --batch-size 100
```

The backfill reads existing profile data and writes only to the separate `UserEmbedding` collection.

## Tests

Run the test suite with:

```bash
uv run python -m unittest discover -s tests -v
```

## Planned Work

- Connect profile updates from the main AU Connect application
- Improve error handling and retry behavior
- Add embedding cleanup when a user is deleted
- Evaluate recommendations with realistic user profiles
- Tune ranking weights based on testing and feedback

## Job Recommendations

`GET /recommendations/jobs/{user_id}?limit=10` requires
`x-internal-service-key`; IDs must be MongoDB ObjectIds and limit is 1–50
(default 10, invalid values return 422). Unknown users return an empty list.

The response is `{"recommendations": [{"jobPostId": "...", "score": 0.8,
"coverage": 1.0, "breakdown": {"semantic": 0.8, "skills": 1.0,
"location": 0.0, "freshness": 1.0}}]}`. Scores are internal ranking information,
not probabilities or frontend match percentages.

Ranking uses semantic similarity (0.55), exact Skill ID overlap (0.25), location
compatibility (0.15), and freshness (0.05). Semantic evidence uses existing user
vectors for title/about/experience/education with weights 0.25/0.25/0.25/0.15;
experience and education each average all their distinct text-vector comparisons
to the job passage. Missing fields reweight the available semantic components.
Top-level unavailable components similarly reweight; coverage is the sum of
original available top-level weights. No selected user skills or no required job
skills makes skills unavailable. Remote location scores 1; onsite/hybrid use
exact Unicode-normalized, whitespace-collapsed, case-insensitive location equality
(or null for missing data). Freshness is `0.5 ** (max(age_days, 0) / 30)`.
Results sort by unrounded score descending, creation date descending, then job ID
ascending; only serialization rounds to six decimals.

Only open, unexpired, unfilled jobs with an existing VISIBLE parent Post qualify.
Own jobs and all previously applied jobs are excluded. **Next.js must perform the
final visibility/access check when hydrating these IDs**, including any audience
or community restrictions and changes since ranking. No Next.js adapter is
included here. Reads use batched queries and explicit safe-field projections;
resumes, contact details, OAuth IDs and verification documents are never loaded.
The supplied schema omits UserSkill; this service expects its `userId` and
`skillId` fields to be BSON ObjectIds.

`JobEmbedding` stores jobPostId (unique startup index), embedding, model identity,
sourceHash, normalizedText, createdAt and updatedAt. It reuses valid 384-dimensional
finite vectors with matching model/hash. Job title/details, sorted canonical skill
names, employment type and location type form a normalized E5 `passage:` using
the existing multilingual-e5-small singleton; salary, company, actual location and
operational metadata are excluded. UserEmbedding reuse follows the existing
model/source-hash validation. There is no Vector Search or stored recommendation
list, and JobPost documents are not modified.

```bash
curl 'http://127.0.0.1:8000/recommendations/jobs/6929aa8767c252bdb59d218f?limit=10' \
  -H 'x-internal-service-key: YOUR_INTERNAL_API_KEY'
curl -X PUT 'http://127.0.0.1:8000/internal/jobs/6929aa8767c252bdb59d218f/embedding' \
  -H 'x-internal-service-key: YOUR_INTERNAL_API_KEY'
curl -X DELETE 'http://127.0.0.1:8000/internal/jobs/6929aa8767c252bdb59d218f/embedding' \
  -H 'x-internal-service-key: YOUR_INTERNAL_API_KEY'
uv run python scripts/backfill_job_embeddings.py --batch-size 100
```

PUT validates existence (404 if absent) then returns 202 and forces recomputation
in BackgroundTasks. DELETE idempotently removes the stored embedding and returns
`jobPostId` and `deleted`. Both authenticate and reject invalid IDs with 422.
Background tasks are in-process; failed refreshes are logged and can be retried.
Backfill scans all jobs by ascending _id, reuses valid records, reports progress
and totals, and exits nonzero on failure. Restarting safely scans from the start
and skips inference for valid records. Batch failures can be retried by rerunning.
