from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from au_connect_recommendation_service.core.embedding_model import (
    get_embedding_model,
)
from au_connect_recommendation_service.db.mongodb import db
from au_connect_recommendation_service.routes.connections import (
    router as connections_router,
)
from au_connect_recommendation_service.routes.internal_embeddings import (
    router as internal_embeddings_router,
)
from au_connect_recommendation_service.services.profile_embeddings import (
    ensure_user_embedding_index,
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    await ensure_user_embedding_index()
    await run_in_threadpool(get_embedding_model)
    yield


app = FastAPI(
    title="AU Connect Recommendation Service",
    lifespan=lifespan,
)

app.include_router(connections_router)
app.include_router(internal_embeddings_router)


@app.get("/health")
async def health():
    await db.command("ping")

    return {
        "status": "ok",
        "database": "connected",
        "embedding_model": "loaded",
    }
