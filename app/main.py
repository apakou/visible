import os

from dotenv.main import load_dotenv
from fastapi import Depends, FastAPI, Form, Request, Response
from sqlalchemy.orm import Session
from twilio.twiml.messaging_response import MessagingResponse

from app.DB.database import SessionLocal, engine
from app.DB.models import Base, Owner
from app.handlers import image_analyzer

Base.metadata.create_all(bind=engine)

app = FastAPI()

load_dotenv()

WHATSAPP_SECRET_KEY = os.getenv("WHATSAPP_SECRET_KEY")


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


@app.get("/webhook")
async def verify(req: Request):
    params = req.query_params

    verify_token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if verify_token == WHATSAPP_SECRET_KEY:
        return Response(content=challenge, status_code=200)

    return Response(content="Forbidden", status_code=403)


@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    print(data, "stuff is here")
    # response = MessagingResponse()

    # 2. Logic: Identify the Trader
    # (Here you would check your 'owners' table for the phone number)

    # 3. Logic: Handle the Input
    # if MediaUrl0:
    #    analysis_result = await image_analyzer.analyze_image_with_deepseek(MediaUrl0)
    #   items = analysis_result["choices"][0]["message"]["content"]

    #   reply = f"I have seen your goods! I found {items}. Is this correct?"
    # else:
    #   reply = f"Received your message: '{Body}'. Processing..."
    #   # TODO: Trigger AI Agent Intent Classifier

    # response.message(reply)
    return Response(content="response is here", status_code=200)
