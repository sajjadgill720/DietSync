"""
app/db/session.py
Database session management and dependency injection for FastAPI.
"""

import os
from typing import Generator
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Automatically load environment variables from .env
load_dotenv()

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/dietsync"

raw_db_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

if raw_db_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg2://" + raw_db_url.split("://", 1)[1]
else:
    database_url = raw_db_url

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding a database session and closing it on completion.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
