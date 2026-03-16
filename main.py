import logging

from fastapi import FastAPI, Form, Response
from twilio.twiml.messaging_response import MessagingResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/message")
async def handle_whatsapp_message(Body: str = Form(...)):
    """Handle incoming WhatsApp messages and reply."""
    response = MessagingResponse()
    msg = response.message(f"You said: {Body}")
    logger.info(f"message: {msg}")
    # Chatbot logic goes here
    return Response(content=str(response), media_type="application/xml")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
