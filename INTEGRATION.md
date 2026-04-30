# OpenOutreach Integration Guide

## Overview

OpenOutreach is a LinkedIn automation API. Your backend sends a job request and gets a `job_id` back immediately. When the job finishes, OpenOutreach POSTs the result to your `callback_url`.

**Base URL:** `http://your-server:8000`

---

## Authentication

All requests require LinkedIn session cookies (`li_at`) passed in the request body. Optionally, a proxy can be assigned per request.

---

## Endpoints

### 1. Send Connection Requests

**`POST /campaign/run`**

Sends connection requests to a list of LinkedIn profiles.

**Request**
```json
{
  "urls": [
    "https://www.linkedin.com/in/johndoe",
    "https://www.linkedin.com/in/janedoe"
  ],
  "cookies": [
    {
      "name": "li_at",
      "value": "YOUR_LI_AT_COOKIE",
      "domain": ".linkedin.com",
      "path": "/",
      "secure": true,
      "httpOnly": true
    }
  ],
  "note": "Hi, I'd love to connect!",
  "proxy": {
    "server": "geo.iproyal.com:12321",
    "username": "myuser_country-us",
    "password": "mypassword"
  },
  "callback_url": "https://yourbackend.com/webhooks/linkedin"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | Yes | LinkedIn profile URLs (max 100) |
| `cookies` | array | Yes* | LinkedIn session cookies |
| `note` | string | No | Connection note (max 300 chars) |
| `proxy` | object | No | Proxy assigned to this account |
| `callback_url` | string | Yes | URL to receive the result |

*Either `cookies` or `username`+`password` required.

**Response (202)**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "queued"
}
```

**Callback Payload**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "completed",
  "result": {
    "success": true,
    "message": "Campaign completed successfully",
    "profiles_processed": 2
  }
}
```

---

### 2. Send a Message

**`POST /message/send`**

Sends a message to an existing LinkedIn connection.

**Request**
```json
{
  "url": "https://www.linkedin.com/in/johndoe",
  "message": "Hey John, just wanted to follow up!",
  "cookies": [
    {
      "name": "li_at",
      "value": "YOUR_LI_AT_COOKIE",
      "domain": ".linkedin.com",
      "path": "/",
      "secure": true,
      "httpOnly": true
    }
  ],
  "proxy": {
    "server": "geo.iproyal.com:12321",
    "username": "myuser_country-us",
    "password": "mypassword"
  },
  "callback_url": "https://yourbackend.com/webhooks/linkedin"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `url` | string | Yes | LinkedIn profile URL |
| `message` | string | Yes | Message to send |
| `cookies` | array | Yes* | LinkedIn session cookies |
| `proxy` | object | No | Proxy assigned to this account |
| `callback_url` | string | Yes | URL to receive the result |

**Response (202)**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "queued"
}
```

**Callback Payload**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "completed",
  "result": {
    "success": true,
    "message": "Message sent successfully",
    "url": "https://www.linkedin.com/in/johndoe",
    "public_identifier": "johndoe",
    "status": "SENT"
  }
}
```

---

### 3. Check Connection Status

**`POST /status`**

Checks whether you are connected to a list of LinkedIn profiles.

**Request**
```json
{
  "urls": [
    "https://www.linkedin.com/in/johndoe"
  ],
  "cookies": [
    {
      "name": "li_at",
      "value": "YOUR_LI_AT_COOKIE",
      "domain": ".linkedin.com",
      "path": "/",
      "secure": true,
      "httpOnly": true
    }
  ],
  "proxy": {
    "server": "geo.iproyal.com:12321",
    "username": "myuser_country-us",
    "password": "mypassword"
  },
  "callback_url": "https://yourbackend.com/webhooks/linkedin"
}
```

**Response (202)**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "queued"
}
```

**Callback Payload**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "completed",
  "result": [
    {
      "url": "https://www.linkedin.com/in/johndoe",
      "public_identifier": "johndoe",
      "state": "CONNECTED",
      "status": "CONNECTED"
    }
  ]
}
```

**Connection States**

| State | Meaning |
|---|---|
| `CONNECTED` | You are connected |
| `PENDING` | Connection request sent, not yet accepted |
| `NOT_CONNECTED` | No connection |
| `ERROR` | Could not check |

---

## Callback Handling

All three endpoints POST to your `callback_url` when the job finishes.

**Failed job example:**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "failed",
  "error": "Login failed – no redirect to feed"
}
```

**Recommended webhook handler (FastAPI):**
```python
@app.post("/webhooks/linkedin")
async def linkedin_callback(payload: dict):
    job_id = payload["job_id"]
    status = payload["status"]   # "completed" or "failed"

    if status == "completed":
        result = payload["result"]
        await db.jobs.update(job_id, {"status": "done", "result": result})

    elif status == "failed":
        error = payload["error"]
        await db.jobs.update(job_id, {"status": "failed", "error": error})

    return {"ok": True}
```

**Recommended webhook handler (Express.js):**
```javascript
app.post('/webhooks/linkedin', express.json(), async (req, res) => {
  const { job_id, status, result, error } = req.body

  if (status === 'completed') {
    await db.jobs.update(job_id, { status: 'done', result })
  } else if (status === 'failed') {
    await db.jobs.update(job_id, { status: 'failed', error })
  }

  res.json({ ok: true })
})
```

---

## Health Check

**`GET /health`**

```json
{
  "status": "healthy",
  "version": "2.0.0"
}
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | RabbitMQ connection URL |
| `QUEUE_NAME` | `openoutreach_jobs` | Queue name |
| `MAX_WORKERS` | `5` | Max concurrent browser sessions |

---

## Running the Server

```bash
# Start RabbitMQ
PATH="/opt/homebrew/opt/erlang@26/bin:$PATH" CONF_ENV_FILE="/opt/homebrew/etc/rabbitmq/rabbitmq-env.conf" /opt/homebrew/opt/rabbitmq/sbin/rabbitmq-server -detached

# Start API
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Start Worker
MAX_WORKERS=5 python -m worker.worker
```
