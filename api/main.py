"""
FastAPI wrapper for LinkedIn OpenOutreach automation

This API provides endpoints to run LinkedIn outreach campaigns
by accepting username, password, and target URLs via HTTP requests.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from api.models import CampaignRequest, CampaignResponse, HealthResponse, StatusResponse
from api.service import CampaignService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize service
campaign_service = CampaignService()

# Thread pool for running sync Playwright code
executor = ThreadPoolExecutor(max_workers=5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events for the application"""
    logger.info("Starting OpenOutreach API...")
    yield
    logger.info("Shutting down OpenOutreach API...")
    executor.shutdown(wait=True)


# Initialize FastAPI app
app = FastAPI(
    title="OpenOutreach API",
    description="API for automating LinkedIn outreach campaigns",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=HealthResponse)
async def root():
    """Root endpoint - health check"""
    return HealthResponse(
        status="healthy",
        version="1.0.0"
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        version="1.0.0"
    )


@app.post("/campaign/run", response_model=CampaignResponse)
async def run_campaign(request: CampaignRequest, background_tasks: BackgroundTasks):
    """
    Run a LinkedIn outreach campaign

    This endpoint accepts LinkedIn credentials and a list of profile URLs,
    then runs the campaign using the existing OpenOutreach functionality.

    Args:
        request: Campaign request containing username, password, and URLs
        background_tasks: FastAPI background tasks

    Returns:
        Campaign response with status and results
    """
    try:
        logger.info(f"Received campaign request for user: {request.username}")
        logger.info(f"Target profiles: {len(request.urls)}")

        # Validate input
        if not request.urls:
            raise HTTPException(
                status_code=400,
                detail="No URLs provided. Please provide at least one LinkedIn profile URL."
            )

        if len(request.urls) > 100:
            raise HTTPException(
                status_code=400,
                detail="Too many URLs. Maximum 100 profiles per request."
            )

        # Run campaign in thread pool to avoid asyncio/Playwright conflict
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            executor,
            campaign_service.run_campaign,
            request.urls,
            request.campaign_name,
            request.username,
            request.password,
            request.cookies
        )

        if result["success"]:
            return CampaignResponse(**result)
        else:
            raise HTTPException(
                status_code=500,
                detail=result["message"]
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in run_campaign: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.post("/campaign/run-async", response_model=CampaignResponse)
async def run_campaign_async(request: CampaignRequest, background_tasks: BackgroundTasks):
    """
    Run a LinkedIn outreach campaign in the background

    This endpoint starts the campaign in a background task and returns immediately.
    Use this for long-running campaigns.

    Args:
        request: Campaign request containing username, password, and URLs
        background_tasks: FastAPI background tasks

    Returns:
        Campaign response with acceptance status
    """
    try:
        logger.info(f"Received async campaign request for user: {request.username}")

        # Validate input
        if not request.urls:
            raise HTTPException(
                status_code=400,
                detail="No URLs provided. Please provide at least one LinkedIn profile URL."
            )

        # Run campaign in background using thread pool
        def run_in_background():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                campaign_service.run_campaign(
                    urls=request.urls,
                    campaign_name=request.campaign_name,
                    username=request.username,
                    password=request.password,
                    cookies=request.cookies
                )
            finally:
                loop.close()

        background_tasks.add_task(
            lambda: executor.submit(run_in_background)
        )

        return CampaignResponse(
            success=True,
            message=f"Campaign '{request.campaign_name}' started in background",
            campaign_id=request.campaign_name,
            profiles_processed=None  # Won't know until complete
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in run_campaign_async: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.post("/status")
async def get_status(request: CampaignRequest):
    """
    Check the status of LinkedIn profiles

    Args:
        request: Contains cookies and URLs to check status for

    Returns:
        Status information for the profiles

    Example:
        POST /status
        {
            "cookies": [{"name": "li_at", "value": "...", ...}],
            "urls": ["https://www.linkedin.com/in/johndoe"]
        }
    """
    try:
        logger.info(f"Status check for {len(request.urls)} profile(s)")

        # Validate input
        if not request.urls:
            raise HTTPException(
                status_code=400,
                detail="At least one URL is required"
            )

        # Create temporary handle and cookies if provided
        handle = None
        cookie_file = None

        if request.cookies:
            # Generate handle for cookie-based auth
            import random
            import string
            handle = 'cookie_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
            cookie_file = campaign_service.create_temporary_cookies_file(request.cookies, handle)
            logger.info(f"Using cookie-based authentication with handle: {handle}")
        elif request.username:
            # Derive handle from username (legacy)
            handle = request.username.split('@')[0].replace('.', '_').replace('-', '_')
        else:
            raise HTTPException(
                status_code=400,
                detail="Either 'cookies' or 'username' must be provided"
            )

        # Get status for each URL
        results = []
        is_cookie_auth = bool(request.cookies)
        for url in request.urls:
            result = campaign_service.get_profile_status_by_handle(handle, url, temp_config=is_cookie_auth)
            results.append(result)

        # Cleanup cookie file
        if cookie_file:
            campaign_service._cleanup_temp_file(cookie_file)

        # Return single result or list depending on input
        return results[0] if len(results) == 1 else results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_status: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )