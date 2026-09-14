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
MONGODB_URI=your_mongodb_connection_string
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
