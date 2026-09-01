from fastapi import FastAPI
from app.db.mongodb import db

app = FastAPI(title="AU Connect Recommendation Service")

@app.get("/health")
def health():
    db.command("ping")
    
    return {
        "status": "ok",
        "database": "connected"
    }
