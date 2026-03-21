from fastapi import FastAPI

from app.DB.database import SessionLocal, engine
from app.DB.models import Base, Owner

Base.metadata.create_all(bind=engine)

app = FastAPI()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
async def root():
    owners = Owner.query.all()
    return {"message": f"Hello, World!, {owners}"}
