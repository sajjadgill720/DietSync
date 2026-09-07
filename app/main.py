"""
app/main.py
Main entry point for the DietSync FastAPI application.

Provides:
- POST /resolve: Synchronous drug resolution (dataset first, DRAP fallback).
- POST /check: Async interaction check enqueueing (returns 202 with job_id).
- GET /check/{job_id}: Polling status endpoint (openFDA sourced citations).
- WS /ws/jobs/{job_id}: Real-time WebSocket notifications via PostgreSQL LISTEN/NOTIFY.
- GET /health: Service health probe.
"""

import logging
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()


from app.routes.check import router as check_router
from app.routes.resolve import router as resolve_router
from app.routes.ws import router as ws_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dietsync_app")

app = FastAPI(
    title="DietSync Clinical Interaction API",
    description=(
        "Clinical drug-drug interaction checker with strict groundedness enforcement. "
        "Resolves Pakistani brand names to generic entities and audits interaction claims "
        "against official manufacturer label texts."
    ),
    version="1.0.0",
)

# CORS configuration for frontend clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(resolve_router)
app.include_router(check_router)
app.include_router(ws_router)


@app.get(
    "/health",
    tags=["System"],
    summary="Health check probe",
)
def health_check():
    return {"status": "healthy", "service": "dietsync-api"}


@app.get(
    "/",
    tags=["System"],
    summary="Root metadata",
)
def root():
    return {
        "service": "DietSync API",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
    }
