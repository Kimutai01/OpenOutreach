"""
OpenOutreach Worker

Consumes jobs from RabbitMQ, runs them in isolated processes (Playwright),
and POSTs the result to the callback_url supplied by the caller.

Usage:
    python -m worker.worker

Environment variables:
    RABBITMQ_URL   amqp://guest:guest@localhost:5672/   (default)
    QUEUE_NAME     openoutreach_jobs                    (default)
    MAX_WORKERS    5                                    (default)
"""
import json
import logging
import os
import signal
import sys
from concurrent.futures import ProcessPoolExecutor, Future

from dotenv import load_dotenv
load_dotenv()

import httpx
import pika

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
QUEUE_NAME   = os.getenv("QUEUE_NAME",   "openoutreach_jobs")
MAX_WORKERS  = int(os.getenv("MAX_WORKERS", "5"))


# ---------------------------------------------------------------------------
# Job runners — defined at module level so ProcessPoolExecutor can pickle them
# ---------------------------------------------------------------------------

def _clear_event_loop():
    import asyncio
    try:
        asyncio.set_event_loop(None)
    except Exception:
        pass


def _run_campaign(job: dict) -> dict:
    _clear_event_loop()
    from api.service import CampaignService
    svc = CampaignService()
    return svc.run_campaign(
        urls          = job["urls"],
        campaign_name = job.get("campaign_name", "connect_follow_up"),
        username      = job.get("username"),
        password      = job.get("password"),
        cookies       = job.get("cookies"),
        message       = job.get("note"),
        proxy         = job.get("proxy"),   # dict or None — proxy kept intact
    )


def _run_message(job: dict) -> dict:
    _clear_event_loop()
    from api.service import CampaignService
    svc = CampaignService()
    return svc.send_message(
        url      = job["url"],
        message  = job["message"],
        cookies  = job.get("cookies"),
        username = job.get("username"),
        password = job.get("password"),
        proxy    = job.get("proxy"),        # dict or None — proxy kept intact
    )


def _run_status(job: dict) -> dict:
    _clear_event_loop()
    from api.service import CampaignService
    svc = CampaignService()
    return svc.check_real_time_connection_status(
        urls     = job["urls"],
        cookies  = job.get("cookies"),
        username = job.get("username"),
        password = job.get("password"),
        proxy    = job.get("proxy"),
    )


def _run_conversation(job: dict) -> dict:
    _clear_event_loop()
    from api.service import CampaignService
    svc = CampaignService()
    return svc.fetch_conversation(
        url      = job["url"],
        cookies  = job.get("cookies"),
        username = job.get("username"),
        password = job.get("password"),
        proxy    = job.get("proxy"),
    )


_RUNNERS = {
    "campaign":     _run_campaign,
    "message":      _run_message,
    "status":       _run_status,
    "conversation": _run_conversation,
}


# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------

def _send_callback(callback_url: str, payload: dict) -> None:
    try:
        resp = httpx.post(callback_url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info("Callback sent → %s  (%d)", callback_url, resp.status_code)
    except Exception as exc:
        logger.error("Callback failed → %s  %s", callback_url, exc)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class Worker:
    def __init__(self):
        self.executor   = ProcessPoolExecutor(max_workers=MAX_WORKERS)
        self.connection = None
        self.channel    = None
        self._in_flight: dict[str, tuple[Future, pika.spec.Basic.Deliver]] = {}

    def connect(self) -> None:
        params = pika.URLParameters(RABBITMQ_URL)
        self.connection = pika.BlockingConnection(params)
        self.channel    = self.connection.channel()
        self.channel.queue_declare(queue=QUEUE_NAME, durable=True)
        # Only send as many unacked messages as we have worker slots
        self.channel.basic_qos(prefetch_count=MAX_WORKERS)
        self.channel.basic_consume(queue=QUEUE_NAME, on_message_callback=self._on_message)
        logger.info("Connected to RabbitMQ — queue=%s  workers=%d", QUEUE_NAME, MAX_WORKERS)

    def _on_message(self, ch, method, properties, body: bytes) -> None:
        try:
            job = json.loads(body)
        except json.JSONDecodeError:
            logger.error("Invalid JSON in message — discarding")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        job_id       = job.get("job_id", "unknown")
        job_type     = job.get("job_type")
        callback_url = job.get("callback_url")

        runner = _RUNNERS.get(job_type)
        if runner is None:
            logger.error("Unknown job_type '%s' for job %s — discarding", job_type, job_id)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        logger.info("Dispatching job %s (type=%s)", job_id, job_type)
        future = self.executor.submit(runner, job)
        self._in_flight[job_id] = (future, method, callback_url)
        future.add_done_callback(lambda f: self._on_done(f, job_id, method.delivery_tag, callback_url))

    def _on_done(self, future: Future, job_id: str, delivery_tag: int, callback_url: str) -> None:
        try:
            result = future.result()
            payload = {"job_id": job_id, "status": "completed", "result": result}
            logger.info("Job %s completed", job_id)
        except Exception as exc:
            payload = {"job_id": job_id, "status": "failed", "error": str(exc)}
            logger.error("Job %s failed: %s", job_id, exc)

        # Send callback
        if callback_url:
            _send_callback(callback_url, payload)

        # Ack the RabbitMQ message (must be called from the connection's thread)
        try:
            self.connection.add_callback_threadsafe(
                lambda: self.channel.basic_ack(delivery_tag=delivery_tag)
            )
        except Exception as exc:
            logger.error("Failed to ack message for job %s: %s", job_id, exc)

        self._in_flight.pop(job_id, None)

    def run(self) -> None:
        self.connect()
        logger.info("Worker started — waiting for jobs…")
        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            logger.info("Shutdown signal received")
            self.channel.stop_consuming()
        finally:
            self.executor.shutdown(wait=True)
            if self.connection and not self.connection.is_closed:
                self.connection.close()
            logger.info("Worker shut down cleanly")


def _handle_signal(sig, frame):
    logger.info("Signal %s received — stopping", sig)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)
    Worker().run()
