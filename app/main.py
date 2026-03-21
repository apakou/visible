from fastapi import Depends, FastAPI, Request
from sqlalchemy.orm import Session
from twilio.twiml.messaging_response import MessagingResponse

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
async def root(db: Session = Depends(get_db)):
    owners = db.query(Owner).all()
    return {"message": f"Hello, World!, {owners}"}


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    incoming_msg_body = form.get("Body", "").strip()
    sender_phone_number = form.get("From", "")

    resp = MessagingResponse()
    if incoming_msg_body.lower() == "hello":
        resp.message("Hi! You sent: " + incoming_msg_body)
    else:
        resp.message("We received your message: " + incoming_msg_body)

    # Twilio expects TwiML (XML) in response
    return str(resp)
