import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DB_URL")

if not DATABASE_URL:
    raise RuntimeError("DB_URL is missing in .env")

if "<pooler-host>" in DATABASE_URL or "<urlencoded_password>" in DATABASE_URL:
    raise RuntimeError(
        "DB_URL still contains placeholders. Paste the real Supabase pooler URI from "
        "Supabase Dashboard -> Project Settings -> Database -> Connection string."
    )

# Common config mistake: using direct DB host with pooler port 6543.
if "@db." in DATABASE_URL and ":6543" in DATABASE_URL:
    raise RuntimeError(
        "DB_URL uses direct Supabase host (db.<project-ref>.supabase.co) with port 6543. "
        "Use the Session/Transaction pooler host from Supabase Dashboard on port 6543, "
        "or use the direct host on port 5432 if your network supports IPv6."
    )

engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    logger.debug("Opened DB session")
    try:
        yield db
    finally:
        db.close()
        logger.debug("Closed DB session")


def init_db_if_sqlite():
    """Create schema automatically for local SQLite runs."""
    if not DATABASE_URL.startswith("sqlite"):
        return

    # Import models so SQLAlchemy registers all mapped tables before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Initialized SQLite schema")
