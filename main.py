import logging

from fastapi import FastAPI, Form, Request, Response
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


@app.post("/webhook")
async def echo_webhook(request: Request):
    data = await request.json()

    print(f"Received webhook: {data}")

    return {"message": "Webhook received", "data": data}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
