"""
Aurora Retriever Service

This service handles two main responsibilities:
1. Scheduled scraping: Runs daily scrapes for all configured scrapers
2. On-demand API: Accepts URLs or document content for immediate processing

Both operations run concurrently without blocking each other.
"""

import asyncio
import logging
from datetime import datetime, time as dt_time
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
import aiohttp
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, HttpUrl, Field
import io

from scrapers.WFA import WFAScraper
from scrapers.base import BaseScraper, Resource
from settings import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress verbose pypdf warnings - only show errors
logging.getLogger('pypdf').setLevel(logging.ERROR)
logging.getLogger('pypdf._reader').setLevel(logging.ERROR)

# Registry of all available scrapers
SCRAPER_REGISTRY = {
    "wfa": WFAScraper,
    # Add more scrapers here as they are implemented
    # "example": ExampleScraper,
}


class DocumentSubmitRequest(BaseModel):
    """Request model for submitting a document or URL"""
    url: Optional[HttpUrl] = Field(None, description="URL to fetch and process")
    title: Optional[str] = Field(None, description="Document title (optional)")
    category: Optional[str] = Field("user_submitted", description="Category/type of document")
    datasource_id: Optional[str] = Field("api_submission", description="Source identifier")
    content: Optional[str] = Field(None, description="Raw text content (if not using URL or file)")


class DocumentSubmitResponse(BaseModel):
    """Response model for document submission"""
    status: str
    message: str
    resource_id: Optional[str] = None


class SchedulerStatus(BaseModel):
    """Status of the scheduler and scrapers"""
    scheduler_running: bool
    next_scheduled_scrape: Optional[str]
    active_scrapes: int
    total_scrapes_today: int


class RetrieverService:
    """
    Main retriever service that manages both scheduled scraping and on-demand processing.
    Uses asyncio to ensure concurrent operations don't block each other.
    """
    
    def __init__(self):
        self.scheduler_task: Optional[asyncio.Task] = None
        self.active_scrapes: Dict[str, asyncio.Task] = {}
        self.scrapes_today: int = 0
        self.last_scrape_date: Optional[str] = None
        
    async def start(self):
        """Start the scheduled scraper in the background"""
        logger.info("Starting retriever service with scheduled scraping")
        self.scheduler_task = asyncio.create_task(self._run_scheduler())
        
    async def stop(self):
        """Stop the scheduler and wait for active scrapes to complete"""
        logger.info("Stopping retriever service")
        
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        
        # Wait for active scrapes to complete
        if self.active_scrapes:
            logger.info(f"Waiting for {len(self.active_scrapes)} active scrapes to complete")
            await asyncio.gather(*self.active_scrapes.values(), return_exceptions=True)
    
    async def _run_scheduler(self):
        """
        Background scheduler that runs daily scrapes at a specified time.
        Runs all scrapers from the registry.
        """
        # Schedule time (default: 2 AM daily)
        schedule_hour = getattr(settings, 'scrape_schedule_hour', 2)
        schedule_minute = getattr(settings, 'scrape_schedule_minute', 0)
        
        logger.info(f"Scheduler started - daily scrapes scheduled for {schedule_hour:02d}:{schedule_minute:02d}")
        
        # Run initial scrape on startup
        await self._run_all_scrapers(scrape_type="startup")
        
        while True:
            try:
                # Calculate time until next scheduled scrape
                now = datetime.now()
                target_time = now.replace(hour=schedule_hour, minute=schedule_minute, second=0, microsecond=0)
                
                # If target time has passed today, schedule for tomorrow
                if now >= target_time:
                    target_time = target_time.replace(day=target_time.day + 1)
                
                wait_seconds = (target_time - now).total_seconds()
                logger.info(f"Next scheduled scrape at {target_time.strftime('%Y-%m-%d %H:%M:%S')} ({wait_seconds/3600:.1f} hours)")
                
                # Wait until scheduled time
                await asyncio.sleep(wait_seconds)
                
                # Run all scrapers
                await self._run_all_scrapers(scrape_type="scheduled")
                
            except asyncio.CancelledError:
                logger.info("Scheduler cancelled")
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)
                # Wait 5 minutes before retrying after error
                await asyncio.sleep(300)
    
    async def _run_all_scrapers(self, scrape_type: str = "scheduled"):
        """
        Run scrape for all registered scrapers concurrently.
        
        Args:
            scrape_type: Type of scrape (startup, scheduled, or manual)
        """
        logger.info(f"Running {scrape_type} scrape for all scrapers: {list(SCRAPER_REGISTRY.keys())}")
        
        # Track scrapes per day
        today = datetime.now().strftime('%Y-%m-%d')
        if self.last_scrape_date != today:
            self.scrapes_today = 0
            self.last_scrape_date = today
        
        # Run all scrapers concurrently
        tasks = []
        for scraper_name, scraper_class in SCRAPER_REGISTRY.items():
            task = asyncio.create_task(
                self._run_single_scraper(scraper_name, scraper_class)
            )
            tasks.append(task)
        
        # Wait for all to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Log results
        for scraper_name, result in zip(SCRAPER_REGISTRY.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"Scraper '{scraper_name}' failed: {result}")
            else:
                logger.info(f"Scraper '{scraper_name}' completed successfully")
        
        self.scrapes_today += 1
        logger.info(f"All {scrape_type} scrapers completed (total today: {self.scrapes_today})")
    
    async def _run_single_scraper(self, scraper_name: str, scraper_class: type):
        """
        Run a single scraper.
        
        Args:
            scraper_name: Name identifier for the scraper
            scraper_class: Scraper class to instantiate
        """
        task_id = f"{scraper_name}_{datetime.now().timestamp()}"
        
        try:
            self.active_scrapes[task_id] = asyncio.current_task()
            
            async with scraper_class() as scraper:
                logger.info(f"Starting scrape: {scraper_name}")
                await scraper.run_scraper()
            
            logger.info(f"Scraper '{scraper_name}' completed successfully")
            
        except Exception as e:
            logger.error(f"Error in scraper '{scraper_name}': {e}", exc_info=True)
            raise
        finally:
            self.active_scrapes.pop(task_id, None)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the retriever service"""
        now = datetime.now()
        schedule_hour = getattr(settings, 'scrape_schedule_hour', 2)
        schedule_minute = getattr(settings, 'scrape_schedule_minute', 0)
        
        target_time = now.replace(hour=schedule_hour, minute=schedule_minute, second=0, microsecond=0)
        if now >= target_time:
            target_time = target_time.replace(day=target_time.day + 1)
        
        return {
            "scheduler_running": self.scheduler_task is not None and not self.scheduler_task.done(),
            "next_scheduled_scrape": target_time.strftime('%Y-%m-%d %H:%M:%S'),
            "active_scrapes": len(self.active_scrapes),
            "total_scrapes_today": self.scrapes_today,
            "registered_scrapers": list(SCRAPER_REGISTRY.keys())
        }


# Global service instance
retriever_service = RetrieverService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - start/stop scheduler"""
    # Startup
    await retriever_service.start()
    yield
    # Shutdown
    await retriever_service.stop()


# Create FastAPI app
app = FastAPI(
    title="Aurora Retriever Service",
    description="Handles scheduled scraping and on-demand document processing",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Root endpoint with service information"""
    return {
        "service": "Aurora Retriever",
        "version": "1.0.0",
        "description": "Scheduled scraping and on-demand document processing"
    }


@app.get("/health")
async def health():
    """Health check endpoint for container orchestration"""
    return {"status": "healthy"}


@app.get("/status", response_model=SchedulerStatus)
async def status():
    """Get current status of the retriever service"""
    status_data = retriever_service.get_status()
    return status_data


@app.post("/submit/url", response_model=DocumentSubmitResponse)
async def submit_url(request: DocumentSubmitRequest):
    """
    Submit a URL for immediate processing.
    
    The URL will be fetched, processed, and sent to the pipeline without waiting
    for the next scheduled scrape.
    
    NOTE: This endpoint is not yet implemented.
    """
    if not request.url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    return DocumentSubmitResponse(
        status="not_implemented",
        message="URL submission endpoint is not yet implemented. Please use scheduled scraping.",
        resource_id=None
    )


@app.post("/submit/content", response_model=DocumentSubmitResponse)
async def submit_content(request: DocumentSubmitRequest):
    """
    Submit raw text content for immediate processing.
    
    The content will be sent directly to the pipeline without fetching.
    
    NOTE: This endpoint is not yet implemented.
    """
    if not request.content:
        raise HTTPException(status_code=400, detail="Content is required")
    
    if not request.title:
        raise HTTPException(status_code=400, detail="Title is required when submitting content")
    
    return DocumentSubmitResponse(
        status="not_implemented",
        message="Content submission endpoint is not yet implemented. Please use scheduled scraping.",
        resource_id=None
    )


@app.post("/submit/file", response_model=DocumentSubmitResponse)
async def submit_file(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    category: str = Form("user_submitted"),
    datasource_id: str = Form("api_submission")
):
    """
    Submit a file for immediate processing.
    
    Supports text files - PDF parsing will use existing scraper capabilities.
    
    NOTE: This endpoint is not yet implemented.
    """
    doc_title = title or file.filename or "Uploaded Document"
    
    return DocumentSubmitResponse(
        status="not_implemented",
        message="File submission endpoint is not yet implemented. Please use scheduled scraping.",
        resource_id=None
    )


@app.post("/scrape/trigger/{scraper_name}")
async def trigger_manual_scrape(scraper_name: str):
    """
    Manually trigger a scrape for a specific scraper.
    
    Args:
        scraper_name: Name of the scraper (e.g., 'wfa')
    
    The scraper will use the configured SCRAPER_MAX_RESOURCES setting to determine
    how many resources to scrape (-1 = unlimited).
    """
    if scraper_name not in SCRAPER_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Scraper '{scraper_name}' not found. Available: {list(SCRAPER_REGISTRY.keys())}"
        )
    
    # Run scraper in background
    asyncio.create_task(
        retriever_service._run_single_scraper(
            scraper_name,
            SCRAPER_REGISTRY[scraper_name]
        )
    )
    
    max_resources = settings.scraper_max_resources
    limit_msg = f"unlimited resources" if max_resources == -1 else f"up to {max_resources} resources"
    
    return {
        "status": "started",
        "message": f"Scrape started for {scraper_name} ({limit_msg})",
        "scraper": scraper_name,
        "max_resources": max_resources
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower()
    )
