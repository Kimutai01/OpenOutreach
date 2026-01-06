"""
FastAPI wrapper for LinkedIn OpenOutreach automation

This API provides endpoints to run LinkedIn outreach campaigns
by accepting username, password, and target URLs via HTTP requests.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import multiprocessing

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from api.models import CampaignRequest, CampaignResponse, HealthResponse, StatusResponse, MessageRequest, MessageResponse
from api.service import CampaignService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize service
campaign_service = CampaignService()

# Standalone functions for ProcessPoolExecutor (must be picklable)
# These functions are defined at module level so they can be pickled
def _run_campaign_wrapper(urls, campaign_name, username, password, cookies, message):
    """Wrapper function for ProcessPoolExecutor - must be at module level"""
    service = CampaignService()
    return service.run_campaign(urls, campaign_name, username, password, cookies, message)

def _check_status_wrapper(urls, cookies, username, password):
    """Wrapper function for ProcessPoolExecutor - must be at module level"""
    service = CampaignService()
    return service.check_real_time_connection_status(urls, cookies, username, password)

def _send_message_wrapper(url, message, cookies, username, password):
    """Wrapper function for ProcessPoolExecutor - must be at module level"""
    service = CampaignService()
    return service.send_message(url, message, cookies, username, password)

# Executor for running sync Playwright code
# Note: Each browser instance uses ~100-200MB RAM
# 
# IMPORTANT: We use ProcessPoolExecutor instead of ThreadPoolExecutor
# because Playwright's sync API detects asyncio event loops even in threads.
# ProcessPoolExecutor provides complete isolation from the asyncio context.
#
# Adjust max_workers based on available resources:
# - 4GB RAM server: max_workers=5-8
# - 8GB RAM server: max_workers=10-15
# - 16GB+ RAM server: max_workers=20-30
# For 100 concurrent users, consider horizontal scaling (multiple instances)
import os
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "5"))  # Default to 5 for processes (more resource-intensive)
USE_PROCESS_POOL = os.getenv("USE_PROCESS_POOL", "true").lower() == "true"

if USE_PROCESS_POOL:
    # ProcessPoolExecutor provides complete isolation - no asyncio context
    # Required for Playwright sync API to work without errors
    executor = ProcessPoolExecutor(max_workers=MAX_WORKERS)
    logger.info(f"Using ProcessPoolExecutor with {MAX_WORKERS} workers for Playwright isolation")
else:
    # ThreadPoolExecutor (legacy - may have asyncio issues)
    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    logger.info(f"Using ThreadPoolExecutor with {MAX_WORKERS} workers (may have asyncio issues)")


def run_sync_playwright(func, *args, **kwargs):
    """
    Wrapper to run Playwright sync code.
    
    If using ProcessPoolExecutor: No wrapper needed - processes are completely isolated
    If using ThreadPoolExecutor: Clear event loop (may not always work)
    
    Note: ProcessPoolExecutor is recommended for Playwright to avoid asyncio detection issues.
    """
    # If we're in a process (ProcessPoolExecutor), we don't need to do anything
    # Processes are completely isolated from the asyncio event loop
    
    # If we're in a thread (ThreadPoolExecutor), try to clear the event loop
    # This may not always work, which is why ProcessPoolExecutor is recommended
    import asyncio
    try:
        # Try to clear event loop (only works in threads, not needed in processes)
        asyncio.set_event_loop(None)
    except Exception:
        # If this fails, we're probably in a process (which is fine)
        pass
    
    # Run the actual function
    return func(*args, **kwargs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events for the application"""
    logger.info("Starting OpenOutreach API...")
    yield
    logger.info("Shutting down OpenOutreach API...")
    executor.shutdown(wait=True)
    # For ProcessPoolExecutor, we need to explicitly shutdown
    if isinstance(executor, ProcessPoolExecutor):
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

        # Run campaign in executor to avoid asyncio/Playwright conflict
        loop = asyncio.get_event_loop()
        if USE_PROCESS_POOL:
            # ProcessPoolExecutor - use standalone function (no wrapper needed)
            result = await loop.run_in_executor(
                executor,
                _run_campaign_wrapper,
                request.urls,
                request.campaign_name,
                request.username,
                request.password,
                request.cookies,
                request.note
            )
        else:
            # ThreadPoolExecutor - use wrapper to clear event loop
            result = await loop.run_in_executor(
                executor,
                run_sync_playwright,
                campaign_service.run_campaign,
                request.urls,
                request.campaign_name,
                request.username,
                request.password,
                request.cookies,
                request.note
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

        # Run campaign in background using executor
        # We need to use asyncio.run_in_executor in the background task
        # to properly execute the campaign in the executor
        async def run_campaign_background():
            """Background task that runs the campaign in the executor"""
            loop = asyncio.get_event_loop()
            try:
                if USE_PROCESS_POOL:
                    # ProcessPoolExecutor - use standalone function
                    await loop.run_in_executor(
                        executor,
                        _run_campaign_wrapper,
                        request.urls,
                        request.campaign_name,
                        request.username,
                        request.password,
                        request.cookies,
                        request.note
                    )
                else:
                    # ThreadPoolExecutor - use wrapper to clear event loop
                    await loop.run_in_executor(
                        executor,
                        run_sync_playwright,
                        campaign_service.run_campaign,
                        request.urls,
                        request.campaign_name,
                        request.username,
                        request.password,
                        request.cookies,
                        request.note
                    )
                logger.info(f"Background campaign '{request.campaign_name}' completed")
            except Exception as e:
                logger.error(f"Error in background campaign '{request.campaign_name}': {e}", exc_info=True)
        
        background_tasks.add_task(run_campaign_background)

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

        if not request.cookies and not request.username:
            raise HTTPException(
                status_code=400,
                detail="Either 'cookies' or 'username' must be provided"
            )

        # Check real-time status by navigating to LinkedIn
        loop = asyncio.get_event_loop()
        if USE_PROCESS_POOL:
            # ProcessPoolExecutor - use standalone function (no wrapper needed)
            results = await loop.run_in_executor(
                executor,
                _check_status_wrapper,
                request.urls,
                request.cookies,
                request.username,
                request.password
            )
        else:
            # ThreadPoolExecutor - use wrapper to clear event loop
            results = await loop.run_in_executor(
                executor,
                run_sync_playwright,
                campaign_service.check_real_time_connection_status,
                request.urls,
                request.cookies,
                request.username,
                request.password
            )

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


@app.post("/message/send", response_model=MessageResponse)
async def send_message(request: MessageRequest):
    """
    Send a message to a LinkedIn profile
    
    This endpoint sends a message to a connected LinkedIn profile.
    Only profiles that are already connected will receive messages.
    Each request sends one message to one profile.
    
    Args:
        request: Message request containing cookies, URL, and message text
        
    Returns:
        Message response with sending result
        
    Example:
        POST /message/send
        {
            "cookies": [{"name": "li_at", "value": "...", ...}],
            "url": "https://www.linkedin.com/in/johndoe",
            "message": "Hi! I'd love to connect."
        }
    """
    try:
        logger.info(f"Received message request for profile: {request.url}")
        logger.info(f"Message length: {len(request.message)} characters")
        
        # Validate authentication
        has_cookies = request.cookies and len(request.cookies) > 0
        has_credentials = request.username and request.password
        
        if not has_cookies and not has_credentials:
            raise HTTPException(
                status_code=400,
                detail="Either 'cookies' or both 'username' and 'password' must be provided"
            )
        
        # Validate input
        if not request.url or not request.url.strip():
            raise HTTPException(
                status_code=400,
                detail="URL is required and cannot be empty."
            )
        
        if not request.message or not request.message.strip():
            raise HTTPException(
                status_code=400,
                detail="Message is required and cannot be empty."
            )
        
        # Send message in executor to avoid asyncio/Playwright conflict
        loop = asyncio.get_event_loop()
        if USE_PROCESS_POOL:
            # ProcessPoolExecutor - use standalone function (no wrapper needed)
            result = await loop.run_in_executor(
                executor,
                _send_message_wrapper,
                request.url,
                request.message,
                request.cookies,
                request.username,
                request.password
            )
        else:
            # ThreadPoolExecutor - use wrapper to clear event loop
            result = await loop.run_in_executor(
                executor,
                run_sync_playwright,
                campaign_service.send_message,
                request.url,
                request.message,
                request.cookies,
                request.username,
                request.password
            )
        
        return MessageResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in send_messages: {str(e)}", exc_info=True)
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