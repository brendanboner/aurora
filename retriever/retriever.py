"""
Aurora Retriever Service

This service handles two main responsibilities:
1. Scheduled scraping: Runs daily scrapes for all configured scrapers
2. On-demand API: Accepts URLs or document content for immediate processing

Both operations run concurrently without blocking each other.
"""

import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List, Type
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from pydantic import BaseModel, HttpUrl, Field

from scrapers import WFAScraper, WFACausewayScraper
from scrapers.base import BaseScraper, Resource
from config_manager import ConfigManager
from settings import settings
from common.auth_middleware import get_user_context, require_role

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress verbose pypdf warnings - only show errors
logging.getLogger('pypdf').setLevel(logging.ERROR)
logging.getLogger('pypdf._reader').setLevel(logging.ERROR)

# Registry mapping scraper_type to scraper class
# The scraper_type value in the database determines which class handles a datasource
SCRAPER_CLASSES: Dict[str, Type[BaseScraper]] = {
    "wfa": WFAScraper,
    "wfa_causeway": WFACausewayScraper,
}

logger.info(f"Available scraper types: {list(SCRAPER_CLASSES.keys())}")


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
        self.config_manager: Optional[ConfigManager] = None
        
    async def start(self):
        """Start the scheduled scraper in the background"""
        logger.info("Starting retriever service with scheduled scraping")
        # Create a single ConfigManager instance for reuse
        self.config_manager = ConfigManager()
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
        
        # Close database connection
        if self.config_manager:
            self.config_manager.close()
            self.config_manager = None
    
    async def _run_scheduler(self):
        """
        Background scheduler that polls for due datasources based on cron schedules.
        
        The scheduler:
        1. Runs startup datasources (run_on_startup=true) immediately
        2. Polls every minute for datasources whose cron schedule is due
        3. Detects missed windows (if last_scraped_at < previous scheduled time)
        """
        poll_interval = getattr(settings, 'scheduler_poll_interval', 60)  # Default: 60 seconds
        
        logger.info(f"Scheduler started - polling every {poll_interval} seconds for due datasources")
        
        # Run startup datasources on service start
        await self._run_startup_datasources()
        
        while True:
            try:
                # Poll for datasources that are due based on cron schedule
                await self._run_due_datasources()
                
                # Wait before next poll
                await asyncio.sleep(poll_interval)
                
            except asyncio.CancelledError:
                logger.info("Scheduler cancelled")
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)
                # Wait before retrying after error
                await asyncio.sleep(poll_interval)
    
    async def _run_startup_datasources(self):
        """
        Run datasources marked with run_on_startup=true.
        Called once when the service starts.
        """
        startup_datasources = self.config_manager.get_startup_datasources()
        
        if not startup_datasources:
            logger.info("No datasources configured to run on startup")
            return
        
        logger.info(f"Running {len(startup_datasources)} startup datasource(s):")
        for ds in startup_datasources:
            ds_id = ds.get('datasource_id', 'unknown')
            ds_name = ds.get('name', ds_id)
            ds_url = ds.get('resource_url', 'N/A')
            logger.info(f"  - {ds_name} ({ds_id}) - URL: {ds_url}")
        
        # Group by scraper_type for session reuse
        grouped = {}
        for ds in startup_datasources:
            scraper_type = ds.get('scraper_type', 'unknown')
            if scraper_type not in grouped:
                grouped[scraper_type] = []
            grouped[scraper_type].append(ds)
        
        await self._run_grouped_datasources(grouped, scrape_type="startup")
    
    async def _run_due_datasources(self):
        """
        Run datasources whose cron schedule is due or was missed.
        Also checks for datasources due for a full refresh.
        Called on each poll interval.
        """
        due_datasources = self.config_manager.get_due_datasources()
        due_ids = {ds.get('datasource_id') for ds in due_datasources}
        
        # Check for full refresh datasources
        full_refresh_datasources = self.config_manager.get_full_refresh_datasources()
        full_refresh_ids = {ds.get('datasource_id') for ds in full_refresh_datasources}
        
        if full_refresh_datasources:
            logger.info(f"Found {len(full_refresh_datasources)} datasource(s) due for FULL REFRESH:")
            for ds in full_refresh_datasources:
                ds_id = ds.get('datasource_id', 'unknown')
                ds_name = ds.get('name', ds_id)
                ds_schedule = ds.get('full_refresh_schedule', 'N/A')
                logger.info(f"  - {ds_name} ({ds_id}) - full refresh schedule: {ds_schedule}")
                
                # Add full refresh datasources to due list if not already there
                if ds_id not in due_ids:
                    ds['is_full_refresh'] = True
                    due_datasources.append(ds)
                    due_ids.add(ds_id)
        
        if not due_datasources:
            # No datasources due - this is normal, just return quietly
            return
        
        logger.info(f"Found {len(due_datasources)} datasource(s) due for scraping:")
        for ds in due_datasources:
            ds_id = ds.get('datasource_id', 'unknown')
            ds_name = ds.get('name', ds_id)
            ds_schedule = ds.get('scrape_schedule', 'N/A')
            last_scraped = ds.get('last_scraped_at')
            last_scraped_str = last_scraped.isoformat() if last_scraped else 'never'
            
            # Mark if this is a full refresh run (may already be marked above)
            is_full_refresh = ds_id in full_refresh_ids
            if is_full_refresh:
                ds['is_full_refresh'] = True
                logger.info(f"  - {ds_name} ({ds_id}) [FULL REFRESH]")
            else:
                logger.info(f"  - {ds_name} ({ds_id})")
            logger.info(f"    Schedule: {ds_schedule}, Last scraped: {last_scraped_str}")
        
        # Group by scraper_type for session reuse
        grouped = {}
        for ds in due_datasources:
            scraper_type = ds.get('scraper_type', 'unknown')
            if scraper_type not in grouped:
                grouped[scraper_type] = []
            grouped[scraper_type].append(ds)
        
        await self._run_grouped_datasources(grouped, scrape_type="scheduled")
    
    async def _run_grouped_datasources(self, grouped_datasources: Dict[str, List[Dict[str, Any]]], scrape_type: str):
        """
        Run datasources grouped by scraper_type.
        
        Args:
            grouped_datasources: Dict mapping scraper_type to list of datasource configs
            scrape_type: Type of scrape (startup, scheduled, manual)
        """
        if not grouped_datasources:
            return
        
        # Track scrapes per day
        today = datetime.now().strftime('%Y-%m-%d')
        if self.last_scrape_date != today:
            self.scrapes_today = 0
            self.last_scrape_date = today
        
        # Process each scraper type
        for scraper_type, datasources in grouped_datasources.items():
            scraper_class = SCRAPER_CLASSES.get(scraper_type)
            
            if not scraper_class:
                logger.warning(f"Unknown scraper_type '{scraper_type}' - skipping {len(datasources)} datasources")
                continue
            
            logger.info(f"Running {scraper_type} scraper for {len(datasources)} datasource(s)")
            
            try:
                await self._run_scraper_for_datasources(scraper_type, scraper_class, datasources)
            except Exception as e:
                logger.error(f"Error running {scraper_type} scraper: {e}", exc_info=True)
        
        self.scrapes_today += 1
        logger.info(f"Completed {scrape_type} scrape (total today: {self.scrapes_today})")
    
    async def _run_scraper_for_datasources(
        self, 
        scraper_type: str, 
        scraper_class: Type[BaseScraper], 
        datasources: List[Dict[str, Any]]
    ):
        """
        Run a single scraper instance for multiple datasources.
        
        This allows session reuse (e.g., single authentication for Causeway).
        
        Args:
            scraper_type: The scraper type identifier
            scraper_class: Scraper class to instantiate
            datasources: List of datasource configurations to process
        """
        task_id = f"{scraper_type}_{datetime.now().timestamp()}"
        
        try:
            self.active_scrapes[task_id] = asyncio.current_task()
            
            # Create single scraper instance for all datasources of this type
            async with scraper_class() as scraper:
                logger.info(f"Started {scraper_type} scraper session")
                
                for ds_config in datasources:
                    datasource_id = ds_config.get('datasource_id', 'unknown')
                    datasource_name = ds_config.get('name', datasource_id)
                    is_full_refresh = ds_config.get('is_full_refresh', False)
                    
                    try:
                        refresh_mode = " (FULL REFRESH)" if is_full_refresh else ""
                        logger.info(f"Processing datasource: {datasource_name}{refresh_mode}")
                        await scraper.run_scraper(ds_config)
                        logger.info(f"Completed datasource: {datasource_name}")
                        
                    except Exception as e:
                        logger.error(f"Error processing {datasource_name}: {e}", exc_info=True)
                        # Continue with next datasource
                        continue
            
            logger.info(f"Completed {scraper_type} scraper session")
            
        except Exception as e:
            logger.error(f"Error in {scraper_type} scraper session: {e}", exc_info=True)
            raise
        finally:
            self.active_scrapes.pop(task_id, None)
    
    async def _run_single_scraper(self, scraper_name: str, scraper_class: type):
        """
        Run a single scraper (legacy method for backwards compatibility).
        
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
        # Get datasources and their schedules from database
        config_manager = ConfigManager()
        try:
            grouped_datasources = config_manager.get_datasources_by_scraper_type()
            all_datasources = config_manager.get_all_scheduled_datasources()
            
            datasource_count = sum(len(ds_list) for ds_list in grouped_datasources.values())
            poll_interval = getattr(settings, 'scheduler_poll_interval', 60)
            
            # Collect schedule info for each datasource
            datasource_schedules = [
                {
                    "datasource_id": ds.get('datasource_id'),
                    "name": ds.get('name'),
                    "schedule": ds.get('scrape_schedule'),
                    "run_on_startup": ds.get('run_on_startup'),
                    "last_scraped_at": ds.get('last_scraped_at').isoformat() if ds.get('last_scraped_at') else None
                }
                for ds in all_datasources
            ]
            
            return {
                "scheduler_running": self.scheduler_task is not None and not self.scheduler_task.done(),
                "poll_interval_seconds": poll_interval,
                "active_scrapes": len(self.active_scrapes),
                "total_scrapes_today": self.scrapes_today,
                "available_scraper_types": list(SCRAPER_CLASSES.keys()),
                "active_scraper_types": list(grouped_datasources.keys()),
                "total_datasources": datasource_count,
                "datasource_schedules": datasource_schedules
            }
        finally:
            config_manager.close()


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
async def status(user: Optional[dict] = Depends(get_user_context)):
    """
    Get current status of the retriever service.
    
    Can be called by authenticated users OR internal services.
    """
    if user:
        logger.info(f"Status check by user {user['email']} (role: {user['role']})")
    
    status_data = retriever_service.get_status()
    return status_data


@app.post("/submit/url", response_model=DocumentSubmitResponse)
@require_role(["admin", "superadmin"])
async def submit_url(request: DocumentSubmitRequest, user: Optional[dict] = Depends(get_user_context)):
    """
    Submit a URL for immediate processing.
    Requires admin or superadmin role.
    
    The URL will be fetched, processed, and sent to the pipeline without waiting
    for the next scheduled scrape.
    
    NOTE: This endpoint is not yet implemented.
    """
    logger.info(f"URL submission by {user['email']} (role: {user['role']}): {request.url}")
    
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



@app.post("/scrape/datasource/{datasource_id}")
@require_role(["admin", "superadmin"])
async def trigger_datasource_scrape(datasource_id: str, user: Optional[dict] = Depends(get_user_context)):
    """
    Manually trigger a scrape for a single datasource.
    Requires admin or superadmin role.
    
    Args:
        datasource_id: The datasource identifier (e.g., 'wfa_causeway_wifi7mtg')
    
    Note: For Causeway datasources, consider using /scrape/all to share authentication.
    """
    logger.info(f"Manual datasource scrape triggered by {user['email']} (role: {user['role']}): {datasource_id}")
    
    config_manager = ConfigManager()
    try:
        datasource = config_manager.get_datasource_config(datasource_id)
        
        # Check if datasource exists and has a scraper_type
        if not datasource.get('scraper_type'):
            raise HTTPException(
                status_code=404,
                detail=f"Datasource '{datasource_id}' not found or has no scraper configured"
            )
        
        scraper_type = datasource['scraper_type']
        
        if scraper_type not in SCRAPER_CLASSES:
            raise HTTPException(
                status_code=400,
                detail=f"Datasource '{datasource_id}' uses unknown scraper type '{scraper_type}'"
            )
        
        datasource_name = datasource.get('name', datasource_id)
        resource_url = datasource.get('resource_url', 'N/A')
        last_scraped = datasource.get('last_scraped_at')
        last_scraped_str = last_scraped.isoformat() if last_scraped else 'never'
        
        logger.info(f"Manual scrape triggered for datasource: {datasource_name} ({datasource_id})")
        logger.info(f"  Scraper: {scraper_type}, URL: {resource_url}, Last scraped: {last_scraped_str}")
        
        # Run scraper in background for just this one datasource
        asyncio.create_task(
            retriever_service._run_scraper_for_datasources(
                scraper_type,
                SCRAPER_CLASSES[scraper_type],
                [datasource]  # Single datasource in list
            )
        )
        
        return {
            "status": "started",
            "message": f"Scrape started for {datasource_name}",
            "datasource_id": datasource_id,
            "datasource_name": datasource_name,
            "scraper_type": scraper_type
        }
    finally:
        config_manager.close()


@app.post("/scrape/datasource/{datasource_id}/collect")
async def collect_datasource_scrape(datasource_id: str, max_items: int = 50):
    """
    Scrape a datasource and return the results as JSON instead of publishing to RabbitMQ.
    
    This is useful for testing/debugging scrapers or previewing what would be scraped.
    The scraper runs synchronously and returns collected messages directly.
    
    Args:
        datasource_id: The datasource identifier (e.g., 'wfa_resource_page')
        max_items: Maximum number of items to collect (default: 50, use -1 for unlimited)
    
    Returns:
        JSON object with collected resources and events
    """
    config_manager = ConfigManager()
    try:
        datasource = config_manager.get_datasource_config(datasource_id)
        
        # Check if datasource exists and has a scraper_type
        if not datasource.get('scraper_type'):
            raise HTTPException(
                status_code=404,
                detail=f"Datasource '{datasource_id}' not found or has no scraper configured"
            )
        
        scraper_type = datasource['scraper_type']
        
        if scraper_type not in SCRAPER_CLASSES:
            raise HTTPException(
                status_code=400,
                detail=f"Datasource '{datasource_id}' uses unknown scraper type '{scraper_type}'"
            )
        
        scraper_class = SCRAPER_CLASSES[scraper_type]
        datasource_name = datasource.get('name', datasource_id)
        
        # Override max_resources in config if max_items specified
        if max_items > 0:
            datasource['max_resources'] = max_items
        
        logger.info(f"Collect scrape for datasource: {datasource_name} ({datasource_id}), max_items={max_items}")
    finally:
        config_manager.close()
    
    try:
        async with scraper_class() as scraper:
            # Enable collect mode
            scraper.enable_collect_mode()
            
            # Run the scraper
            await scraper.run_scraper(datasource)
            
            # Get collected messages
            messages = scraper.get_collected_messages()
            
            # Separate resources and events
            resources = [m for m in messages if m.get('message_type') == 'resource']
            events = [m for m in messages if m.get('message_type') == 'event']
            
            return {
                "status": "success",
                "datasource_id": datasource_id,
                "datasource_name": datasource_name,
                "scraper_type": scraper_type,
                "total_collected": len(messages),
                "resources_count": len(resources),
                "events_count": len(events),
                "resources": resources,
                "events": events
            }
            
    except Exception as e:
        logger.error(f"Error in collect scrape for {datasource_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error scraping datasource: {str(e)}"
        )


@app.post("/scrape/all")
@require_role(["admin", "superadmin"])
async def trigger_scrape_all(user: Optional[dict] = Depends(get_user_context)):
    """
    Manually trigger a scrape for all configured datasources.
    Requires admin or superadmin role.
    
    Datasources are grouped by scraper_type to allow session reuse 
    (e.g., single Causeway authentication for all Causeway datasources).
    
    Returns list of scraper types started and their datasources.
    """
    logger.warning(f"Manual scrape of ALL datasources triggered by {user['email']} (role: {user['role']})")
    
    config_manager = ConfigManager()
    try:
        grouped_datasources = config_manager.get_datasources_by_scraper_type()
        
        if not grouped_datasources:
            return {
                "status": "no_datasources",
                "message": "No active datasources found with scraper types configured",
                "scraper_types": []
            }
        
        started = []
        skipped = []
        
        for scraper_type, datasources in grouped_datasources.items():
            if scraper_type not in SCRAPER_CLASSES:
                skipped.append({
                    "scraper_type": scraper_type,
                    "reason": f"Unknown scraper type",
                    "datasources": [ds.get('datasource_id') for ds in datasources]
                })
                continue
            
            datasource_info = [
                {"datasource_id": ds.get('datasource_id'), "name": ds.get('name', ds.get('datasource_id'))}
                for ds in datasources
            ]
            
            logger.info(f"Manual scrape triggered for scraper type '{scraper_type}' with {len(datasources)} datasource(s)")
            for ds in datasources:
                logger.info(f"  - {ds.get('name', ds.get('datasource_id'))} ({ds.get('datasource_id')})")
            
            # Run scraper in background
            asyncio.create_task(
                retriever_service._run_scraper_for_datasources(
                    scraper_type,
                    SCRAPER_CLASSES[scraper_type],
                    datasources
                )
            )
            
            started.append({
                "scraper_type": scraper_type,
                "datasources": datasource_info
            })
        
        total_datasources = sum(len(s["datasources"]) for s in started)
        
        return {
            "status": "started",
            "message": f"Scrape started for {total_datasources} datasource(s) across {len(started)} scraper type(s)",
            "started": started,
            "skipped": skipped
        }
    finally:
        config_manager.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower()
    )
