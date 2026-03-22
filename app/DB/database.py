import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

load_dotenv()
database_url = os.getenv("DATABASE_URL")

if database_url is None:
    raise ValueError("DATABASE_URL environment variable not set")

engine = create_engine(database_url, echo=True, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
