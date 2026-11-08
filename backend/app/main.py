"""Minimal FastAPI application shell for local development."""

from fastapi import FastAPI, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_engine
from app.documents.api import router as knowledge_documents_router
from app.api.v1.analysis import router as analysis_router
from app.api.v1.evidence import router as evidence_router
from app.api.v1.governance import router as governance_router
from app.api.v1.reviews import router as reviews_router
from app.api.v1.submissions import router as submissions_router

app = FastAPI(title="VerityAI API", version="0.1.0")
app.include_router(knowledge_documents_router)
app.include_router(submissions_router)
app.include_router(reviews_router)
app.include_router(analysis_router)
app.include_router(governance_router)
app.include_router(evidence_router)

@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    """Report that the API process is running."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness(response: Response) -> dict[str, str]:
    """Verify the API can execute a simple query against PostgreSQL."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except (RuntimeError, SQLAlchemyError):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": "unavailable"}
    return {"status": "ok", "database": "ok"}
