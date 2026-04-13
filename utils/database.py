"""
Database connection and session management.
Supports PostgreSQL (production) and SQLite (development).
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from utils.models import Base

load_dotenv()

_engine = None
SessionLocal = sessionmaker(autocommit=False, autoflush=False)


def get_database_url() -> str:
    """Return a normalized database URL suitable for SQLAlchemy."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return "sqlite:///./traffic.db"

    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://"):]

    if "supabase.co" in database_url and "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url



def get_engine():
    """Create the engine lazily so imports do not crash serverless functions."""
    global _engine
    if _engine is not None:
        return _engine

    database_url = get_database_url()
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine_kwargs = {
        "connect_args": connect_args,
        "pool_pre_ping": True,
        "echo": False,
    }
    if not database_url.startswith("sqlite"):
        engine_kwargs["poolclass"] = NullPool
    _engine = create_engine(database_url, **engine_kwargs)
    SessionLocal.configure(bind=_engine)
    return _engine


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=get_engine())


def get_db() -> Session:
    """Get a database session. Caller must close it."""
    get_engine()
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


def get_db_context():
    """Context manager for database sessions."""
    get_engine()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_db_connection() -> bool:
    """Verify database connectivity."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
