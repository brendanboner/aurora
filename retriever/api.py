# Scraper API Service - HTTP endpoint to trigger scraping
import asyncio
import logging
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from scrapers.WFA import WFAScraper
from typing import Optional
from settings import settings

app = FastAPI(title="Aurora Scraper API")

class ScrapeRequest(BaseModel):
    scraper_type: str = "wfa"  # Future: support multiple scrapers
    full_scrape: bool = False  # True for full scrape, False for daily
    queue_name: Optional[str] = None

class ScrapeResponse(BaseModel):
    status: str
    message: str
    task_id: Optional[str] = None

# Store running tasks
running_tasks = {}

@app.get("/")
async def root():
    return {"message": "Aurora Scraper API", "status": "ready"}

@app.get("/health")
async def health():
    """Simple health endpoint for container healthchecks."""
    return {"status": "ok"}

@app.get("/status")
async def status():
    return {
        "running_tasks": len(running_tasks),
        "tasks": list(running_tasks.keys())
    }

@app.post("/scrape", response_model=ScrapeResponse)
async def trigger_scrape(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """Trigger a scraping job"""
    
    task_id = f"{request.scraper_type}_{request.full_scrape}_{len(running_tasks)}"
    
    if request.scraper_type == "wfa":
        background_tasks.add_task(
            run_wfa_scraper, 
            task_id, 
            request.full_scrape,
        )
        
        return ScrapeResponse(
            status="started",
            message=f"{'Full' if request.full_scrape else 'Daily'} WFA scraping started",
            task_id=task_id
        )
    else:
        return ScrapeResponse(
            status="error",
            message=f"Unknown scraper type: {request.scraper_type}"
        )

async def run_wfa_scraper(task_id: str, full_scrape: bool):
    """Background task to run WFA scraper"""
    running_tasks[task_id] = {"status": "running", "type": "wfa", "full_scrape": full_scrape}
    
    try:
        async with WFAScraper() as scraper:
            if full_scrape:
                await scraper.run_full_scraper()
            else:
                await scraper.run_scraper()
        
        running_tasks[task_id]["status"] = "completed"
        logging.info(f"Scraper task {task_id} completed successfully")
        
    except Exception as e:
        running_tasks[task_id]["status"] = "failed"
        running_tasks[task_id]["error"] = str(e)
        logging.error(f"Scraper task {task_id} failed: {e}")

if __name__ == "__main__":
    # Configure logging from settings
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    import uvicorn
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)