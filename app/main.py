import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Visbl MVP v1")


@app.on_event("startup")
def on_startup():
    from app.database import init_db

    init_db()
    logger.info("DB initialised")


@app.get("/")
async def root():
    return {"message": "Visbl is running"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/message")
async def handle_whatsapp_message(
    Body: str = Form(...), From: str = Form(...), request: Request = None
):
    # from app.router import route_message

    from app.database import SessionLocal
    from app.models import Owner

    db = SessionLocal()
    phone = From.replace("whatsapp:", "")

    try:
        reply_text = "reply"
        # reply_text = route_message(phone=phone, message=Body, db=db)
    except Exception as e:
        logger.error(f"Error routing message from {phone}: {e}")
        reply_text = "Something went wrong — please try again."
    finally:
        db.close()

    response = MessagingResponse()
    response.message(reply_text)
    logger.info(f"Reply to {phone}: {reply_text}")
    return Response(content=str(response), media_type="application/xml")


@app.post("/webhook")
async def echo_webhook(request: Request):
    data = await request.json()
    logger.info(f"Received webhook: {data}")
    return {"message": "Webhook received", "data": data}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
