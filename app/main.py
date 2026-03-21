from fastapi import Depends, FastAPI, Form
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
async def whatsapp_webhook(
    From: str = Form(...),
    Body: str = Form(...),
    MediaUrl0: str = Form(None),
):
    response = MessagingResponse()

    # 2. Logic: Identify the Trader
    # (Here you would check your 'owners' table for the phone number)

    # 3. Logic: Handle the Input
    if MediaUrl0:
        reply = "I see your photo! Let me analyze your stock..."
        # TODO: Trigger Step 3 (Claude Vision Parser)
    else:
        reply = f"Received your message: '{Body}'. Processing..."
        # TODO: Trigger AI Agent Intent Classifier

    # 4. Send the reply back to WhatsApp
    response.message(reply)
    return str(response)
