"""
FastAPI wrapper for LinkedIn OpenOutreach automation

Requests are queued in RabbitMQ and processed by worker/worker.py.
Each endpoint returns a job UUID immediately (HTTP 202).
When the job finishes the worker POSTs the result to callback_url.
"""
import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

import pika
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.models import (
    CampaignRequest,
    ConversationRequest,
    HealthResponse,
    MessageRequest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
QUEUE_NAME   = os.getenv("QUEUE_NAME", "openoutreach_jobs")

# Thread pool used only for blocking pika publish calls (publish is fast, ~1 ms)
_publish_executor = ThreadPoolExecutor(max_workers=4)


def _get_rabbit_channel():
    """Open a fresh connection + channel. Called inside a thread."""
    params = pika.URLParameters(RABBITMQ_URL)
    conn   = pika.BlockingConnection(params)
    ch     = conn.channel()
    ch.queue_declare(queue=QUEUE_NAME, durable=True)
    return conn, ch


def _publish_blocking(payload: dict) -> None:
    """Publish one job message to RabbitMQ. Runs in a thread."""
    conn, ch = _get_rabbit_channel()
    try:
        ch.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=json.dumps(payload),
            properties=pika.BasicProperties(
                delivery_mode=2,          # persistent
                content_type="application/json",
            ),
        )
    finally:
        conn.close()


async def publish_job(payload: dict) -> None:
    """Async wrapper — runs the blocking publish in a thread so FastAPI doesn't stall."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_publish_executor, _publish_blocking, payload)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting OpenOutreach API…")
    yield
    logger.info("Shutting down OpenOutreach API…")
    _publish_executor.shutdown(wait=False)


app = FastAPI(
    title="OpenOutreach API",
    description="Queues LinkedIn automation jobs via RabbitMQ.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/", response_model=HealthResponse)
@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="healthy", version="2.0.0")


# ---------------------------------------------------------------------------
# Campaign (connection requests)
# ---------------------------------------------------------------------------

@app.post("/campaign/run", status_code=202)
async def run_campaign(request: CampaignRequest):
    """
    Queue a connection-request campaign.
    Returns job_id immediately. Result is POSTed to callback_url when done.
    """
    if not request.urls:
        raise HTTPException(status_code=400, detail="No URLs provided.")
    if len(request.urls) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 URLs per request.")

    job_id = str(uuid.uuid4())
    payload = {
        "job_id":        job_id,
        "job_type":      "campaign",
        "callback_url":  request.callback_url,
        "urls":          request.urls,
        "campaign_name": request.campaign_name,
        "username":      request.username,
        "password":      request.password,
        "cookies":       request.cookies,
        "note":          request.note,
        "proxy":         request.proxy.model_dump() if request.proxy else None,
    }

    await publish_job(payload)
    logger.info("Queued campaign job %s (%d URLs)", job_id, len(request.urls))
    return {"job_id": job_id, "status": "queued"}


# ---------------------------------------------------------------------------
# Message sending
# ---------------------------------------------------------------------------

@app.post("/message/send", status_code=202)
async def send_message(request: MessageRequest):
    """
    Queue a message-send job.
    Returns job_id immediately. Result is POSTed to callback_url when done.
    """
    if not request.url:
        raise HTTPException(status_code=400, detail="URL is required.")
    if not request.message:
        raise HTTPException(status_code=400, detail="Message is required.")

    has_auth = (request.cookies and len(request.cookies) > 0) or (request.username and request.password)
    if not has_auth:
        raise HTTPException(status_code=400, detail="Either cookies or username/password required.")

    job_id = str(uuid.uuid4())
    payload = {
        "job_id":       job_id,
        "job_type":     "message",
        "callback_url": request.callback_url,
        "url":          request.url,
        "message":      request.message,
        "username":     request.username,
        "password":     request.password,
        "cookies":      request.cookies,
        "proxy":        request.proxy.model_dump() if request.proxy else None,
    }

    await publish_job(payload)
    logger.info("Queued message job %s → %s", job_id, request.url)
    return {"job_id": job_id, "status": "queued"}


# ---------------------------------------------------------------------------
# Connection status check
# ---------------------------------------------------------------------------

@app.post("/status", status_code=202)
async def get_status(request: CampaignRequest):
    """
    Queue a real-time connection-status check.
    Returns job_id immediately. Result is POSTed to callback_url when done.
    """
    if not request.urls:
        raise HTTPException(status_code=400, detail="At least one URL is required.")

    has_auth = (request.cookies and len(request.cookies) > 0) or request.username
    if not has_auth:
        raise HTTPException(status_code=400, detail="Either cookies or username required.")

    job_id = str(uuid.uuid4())
    payload = {
        "job_id":       job_id,
        "job_type":     "status",
        "callback_url": request.callback_url,
        "urls":         request.urls,
        "username":     request.username,
        "password":     request.password,
        "cookies":      request.cookies,
        "proxy":        request.proxy.model_dump() if request.proxy else None,
    }

    await publish_job(payload)
    logger.info("Queued status job %s (%d URLs)", job_id, len(request.urls))
    return {"job_id": job_id, "status": "queued"}


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

@app.post("/messages/get", status_code=202)
async def get_messages(request: ConversationRequest):
    """
    Queue a conversation-fetch job.
    Returns job_id immediately. Result is POSTed to callback_url when done.
    """
    if not request.url:
        raise HTTPException(status_code=400, detail="URL is required.")

    has_auth = (request.cookies and len(request.cookies) > 0) or request.username
    if not has_auth:
        raise HTTPException(status_code=400, detail="Either cookies or username required.")

    job_id = str(uuid.uuid4())
    payload = {
        "job_id":       job_id,
        "job_type":     "conversation",
        "callback_url": request.callback_url,
        "url":          request.url,
        "username":     request.username,
        "password":     request.password,
        "cookies":      request.cookies,
        "proxy":        request.proxy.model_dump() if request.proxy else None,
    }

    await publish_job(payload)
    logger.info("Queued conversation job %s -> %s", job_id, request.url)
    return {"job_id": job_id, "status": "queued"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
