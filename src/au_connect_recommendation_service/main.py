from fastapi import FastAPI

from au_connect_recommendation_service.db.mongodb import db
from au_connect_recommendation_service.routes.connections import router as connections_router

app = FastAPI(
    title="AU Connect Recommendation Service"
)

app.include_router(connections_router)

app = FastAPI(title="AU Connect Recommendation Service")


@app.get("/health")
async def health():
    await db.command("ping")

    return {"status": "ok", "database": "connected"}

app.include_router(connections_router)