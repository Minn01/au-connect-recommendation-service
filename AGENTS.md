# AU Connect Recommendation Service

## Project context

This repository contains the AU Connect recommendation microservice. It is a
Python 3.13 FastAPI service backed by MongoDB, accessed asynchronously through
PyMongo's `AsyncMongoClient` (`db` is configured in
`src/au_connect_recommendation_service/db/mongodb.py`). MongoDB identifiers are
BSON `ObjectId` values; application models expose IDs as strings.

Relevant code is organized as follows:

- `src/au_connect_recommendation_service/routes/`: FastAPI endpoints.
- `src/au_connect_recommendation_service/services/`: recommendation and
  similarity logic.
- `src/au_connect_recommendation_service/models/`: small dataclass models and
  document mapping helpers.
- `src/au_connect_recommendation_service/db/mongodb.py`: shared database
  configuration.

The connection recommendation endpoint is `GET
/recommendations/connections/{user_id}`. Its route calls
`get_connection_recommendations(user_id, limit)` and returns its result in
`data.recommendations`; preserve that API contract unless a coordinated API
change is explicitly requested.

## Connection recommendation behavior

`services/connection_recommender.py` is currently rule-based. Preserve its
current signals and weights unless the task explicitly authorizes a product
change:

1. Find the current user.
2. Exclude existing connections and users with pending connection requests.
3. Fetch active (`accountStatus: "ACTIVE"`) candidate users.
4. Compute mutual-connection counts.
5. Compute profile similarity using `services/similarity.py` unchanged.
6. Score candidates as `mutual_score * 0.60 + profile_score * 0.40`.
7. Sort descending by final score and return at most `limit` results.

Do not introduce NLP, embeddings, caching, additional recommendation signals,
or scoring-weight changes while working on this pipeline.

## MongoDB data conventions

- `User._id`, `Connection.userAId`, `Connection.userBId`,
  `ConnectionRequest.fromUserId`, and `ConnectionRequest.toUserId` are MongoDB
  `ObjectId` values.
- `Connection` is undirected: a relationship may be stored with either user in
  `userAId` or `userBId`. Never assume an ordering.
- Pending connection requests are those with `status: "PENDING"`; both incoming
  and outgoing requests exclude the other user from recommendations.
- Convert strings to `ObjectId` at MongoDB query boundaries. Avoid repeated or
  gratuitous ID conversions, but ensure all BSON-ID query values are
  `ObjectId`s.

## Mutual-connections implementation guidance

Avoid an N+1 pattern. Fetch the current user's connection IDs once in the main
recommendation flow, reuse them for exclusion and mutual-count calculation,
and fetch all candidate connection documents using one batch query (for
example, a `$or` over `userAId: {$in: ...}` and `userBId: {$in: ...}`).

For every batched connection document, identify the candidate endpoint and its
other endpoint, then count it only when that other endpoint is a current-user
connection. Return counts keyed by candidate user ID. The implementation must
work for candidates appearing in either `userAId` or `userBId`.

## Change and verification expectations

Before modifying recommendation code, inspect the route/API consumer, models,
and MongoDB helper so return shapes and conventions remain compatible. Keep the
code direct and readable; add an index only when it is clearly necessary for a
new query, and explain the need before changing schema/index definitions.

After changes, run relevant tests, type checks, or linting available in the
repository. If none exist, verify at least:

- no candidates;
- no mutual connections;
- multiple mutual connections;
- connections stored in either `userAId`/`userBId` direction;
- existing and pending users remain excluded; and
- `limit` is respected.

When reporting a connection-recommendation refactor, state the before/after
MongoDB query behavior for mutual connections and summarize why the result
semantics are unchanged.
