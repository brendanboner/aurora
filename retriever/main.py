import asyncio
import logging
from scrapers.WFA import WFAScraper
from settings import settings


async def main():
    # Configure logging level from settings
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    async with WFAScraper() as scraper:
        # Use run_scraper() for daily updates (first page only)
        # Use run_full_scraper() for complete database population (all pages)
        await scraper.run_scraper()

if __name__ == "__main__":
    asyncio.run(main())