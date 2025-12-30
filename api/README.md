# OpenOutreach API

A FastAPI wrapper for the OpenOutreach LinkedIn automation tool. This API allows you to run LinkedIn outreach campaigns via HTTP requests, providing username, password, and target profile URLs.

## Features

- **Simple REST API** - Run campaigns via HTTP POST requests
- **Multiple Users** - Support different LinkedIn accounts per request
- **Async Support** - Run campaigns in background or synchronously
- **Status Tracking** - Check campaign progress for individual profiles
- **Auto-cleanup** - Temporary files and browsers are automatically cleaned up
- **Parallel Campaigns** - Run up to 5 campaigns simultaneously
- **Full Integration** - Uses all existing OpenOutreach functionality

## Installation

### 1. Install Dependencies

From the project root directory:

```bash
# Install API dependencies
pip install -r api/requirements.txt

# Or if using uv (recommended)
uv pip install -r api/requirements.txt
```

### 2. Start the API Server

```bash
# From project root
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Or run directly:

```bash
cd api
python main.py
```

The API will be available at `http://localhost:8000`

## API Endpoints

### Health Check

**GET** `/` or `/health`

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

### Run Campaign (Synchronous)

**POST** `/campaign/run`

Runs the campaign and waits for completion before responding.

**Request Body:**
```json
{
  "username": "your-email@example.com",
  "password": "your-password",
  "urls": [
    "https://www.linkedin.com/in/johndoe",
    "https://www.linkedin.com/in/janedoe"
  ],
  "campaign_name": "connect_follow_up"
}
```

**Example Request:**
```bash
curl -X POST "http://localhost:8000/campaign/run" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "your-email@example.com",
    "password": "your-password",
    "urls": [
      "https://www.linkedin.com/in/johndoe",
      "https://www.linkedin.com/in/janedoe"
    ],
    "campaign_name": "connect_follow_up"
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "Campaign 'connect_follow_up' completed successfully",
  "campaign_id": "connect_follow_up",
  "profiles_processed": 2
}
```

### Run Campaign (Asynchronous)

**POST** `/campaign/run-async`

Starts the campaign in the background and returns immediately. Use this for long-running campaigns.

**Request Body:** Same as synchronous endpoint

**Example Request:**
```bash
curl -X POST "http://localhost:8000/campaign/run-async" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "your-email@example.com",
    "password": "your-password",
    "urls": [
      "https://www.linkedin.com/in/johndoe",
      "https://www.linkedin.com/in/janedoe"
    ]
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "Campaign 'connect_follow_up' started in background",
  "campaign_id": "connect_follow_up",
  "profiles_processed": null
}
```

### Check Profile Status

**GET** `/status`

Check the status of a specific LinkedIn profile in your campaign database.

**Query Parameters:**
- `username` (required) - Your LinkedIn email
- `url` (required) - LinkedIn profile URL to check
- `password` (optional) - Your LinkedIn password (only needed if account not in YAML config)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/status?username=your-email@example.com&url=https://www.linkedin.com/in/johndoe&password=your-password"
```

**Response (Profile Found):**
```json
{
  "found": true,
  "public_identifier": "johndoe",
  "url": "https://www.linkedin.com/in/johndoe",
  "state": "CONNECTED",
  "full_name": "John Doe",
  "headline": "Software Engineer at Tech Company",
  "last_updated": "2025-12-29T13:05:35.123456"
}
```

**Response (Profile Not Found):**
```json
{
  "found": false,
  "public_identifier": "johndoe",
  "url": "https://www.linkedin.com/in/johndoe",
  "state": "NOT_FOUND",
  "message": "Profile not found in database"
}
```

**Profile States:**
- `DISCOVERED` - URL added to system
- `ENRICHED` - Profile data scraped
- `PENDING` - Ready for connection request
- `CONNECTED` - Connection request sent
- `COMPLETED` - All campaign actions completed
- `FAILED` - Error occurred during processing
- `NOT_FOUND` - Profile not in database yet
- `ERROR` - System error

## Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `username` | string | Yes | - | LinkedIn account username/email |
| `password` | string | Yes | - | LinkedIn account password |
| `urls` | array[string] | Yes | - | List of LinkedIn profile URLs (max 100) |
| `campaign_name` | string | No | "connect_follow_up" | Name of the campaign to run |

## Response Format

### Success Response

```json
{
  "success": true,
  "message": "Campaign 'connect_follow_up' completed successfully",
  "campaign_id": "connect_follow_up",
  "profiles_processed": 10
}
```

### Error Response

```json
{
  "success": false,
  "message": "Campaign failed: [error details]",
  "campaign_id": null,
  "profiles_processed": 0
}
```

## Usage Examples

### Python

```python
import requests

url = "http://localhost:8000/campaign/run"
payload = {
    "username": "your-email@example.com",
    "password": "your-password",
    "urls": [
        "https://www.linkedin.com/in/johndoe",
        "https://www.linkedin.com/in/janedoe"
    ],
    "campaign_name": "connect_follow_up"
}

response = requests.post(url, json=payload)
result = response.json()
print(result)
```

### JavaScript/Node.js

```javascript
const axios = require('axios');

const payload = {
  username: 'your-email@example.com',
  password: 'your-password',
  urls: [
    'https://www.linkedin.com/in/johndoe',
    'https://www.linkedin.com/in/janedoe'
  ],
  campaign_name: 'connect_follow_up'
};

axios.post('http://localhost:8000/campaign/run', payload)
  .then(response => {
    console.log(response.data);
  })
  .catch(error => {
    console.error(error.response.data);
  });
```

### cURL

```bash
curl -X POST "http://localhost:8000/campaign/run" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "your-email@example.com",
    "password": "your-password",
    "urls": [
      "https://www.linkedin.com/in/johndoe"
    ]
  }'
```

## Interactive API Documentation

FastAPI automatically generates interactive API documentation:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

These interfaces allow you to:
- View all endpoints
- Test API calls directly in the browser
- See request/response schemas
- Download OpenAPI specification

## How It Works

1. **Request Received**: API receives credentials and URLs
2. **Temporary Files Created**:
   - Account config YAML with credentials
   - CSV file with target URLs
3. **Campaign Launched**: Uses existing OpenOutreach functionality
4. **Cleanup**: Temporary files are automatically deleted
5. **Response Returned**: Campaign results sent back to client

## Architecture

```
api/
├── __init__.py          # Package initialization
├── main.py              # FastAPI application and endpoints
├── models.py            # Pydantic models for request/response
├── service.py           # Business logic and campaign service
├── requirements.txt     # API dependencies
└── README.md           # This file
```

## Security Considerations

**Important**: This API handles sensitive LinkedIn credentials. Consider these security measures:

1. **HTTPS Only**: Use HTTPS in production (configure reverse proxy like nginx)
2. **Authentication**: Add API key or OAuth authentication
3. **Rate Limiting**: Implement rate limiting to prevent abuse
4. **Input Validation**: Already implemented via Pydantic models
5. **Credential Storage**: Consider encrypting credentials or using a secrets manager
6. **CORS**: Update CORS settings in `main.py` for production

## Production Deployment

### Using Gunicorn

```bash
pip install gunicorn
gunicorn api.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Using Docker

Create `api/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:

```bash
docker build -t openoutreach-api ./api
docker run -p 8000:8000 openoutreach-api
```

## Limitations

- Maximum 100 URLs per request (configurable)
- Credentials are not persisted (must be provided with each request)
- Single campaign per request
- Status tracking requires password parameter if account not in YAML config

## Troubleshooting

### Port Already in Use

```bash
# Use a different port
uvicorn api.main:app --port 8001
```

### Import Errors

Make sure you're running from the project root:

```bash
# From project root, not from api/ directory
python -m uvicorn api.main:app --reload
```

### Browser Issues

The API uses the same Playwright browser automation as the main application. Make sure Playwright is installed:

```bash
playwright install --with-deps chromium
```

## Contributing

This API is a wrapper around the core OpenOutreach functionality. For issues or enhancements:

1. Check the main [OpenOutreach repository](https://github.com/eracle/OpenOutreach)
2. Report API-specific issues separately
3. Follow the existing code structure and patterns

## License

Same as OpenOutreach - GNU GPLv3

## Legal Disclaimer

**Not affiliated with LinkedIn.** Automation may violate LinkedIn's terms. Use at your own risk.