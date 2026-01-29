"""Rollup scheduler for periodic rollup generation.

Runs rollup generation:
1. On startup (initial generation)
2. Periodically based on cron schedule (default: 2 AM daily)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.services.rollup_generator import RollupGenerator
from src.settings import settings

logger = logging.getLogger(__name__)


class RollupScheduler:
    """Scheduler for periodic rollup generation."""
    
    def __init__(self):
        """Initialize scheduler."""
        self.generator = RollupGenerator()
        self._task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._poll_interval = 3600  # Check every hour
        self._target_hour = 2  # Run at 2 AM UTC
        self._last_run_date: Optional[int] = None  # Track last run day
        
    async def start(self):
        """Start the scheduler."""
        if self._task is not None:
            logger.warning("Rollup scheduler already running")
            return
        
        logger.info("Starting rollup scheduler (target hour: %d UTC, check interval: %d seconds)", 
                   self._target_hour, self._poll_interval)
        
        # Run immediately on startup if enabled
        if settings.fast_rollup_generation_enabled:
            logger.info("Running initial rollup generation on startup")
            try:
                await self._run_generation()
            except Exception as e:
                logger.error(f"Initial rollup generation failed: {e}, will use cached rollups if available", exc_info=True)
                logger.warning("Service will continue with stale PostgreSQL cache or direct Neo4j queries")
        
        # Start periodic scheduler
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._run())
    
    async def shutdown(self):
        """Stop the scheduler."""
        if self._task is None:
            return
        
        logger.info("Stopping rollup scheduler")
        self._shutdown_event.set()
        self._task.cancel()
        
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
    
    async def _run(self):
        """Main scheduler loop."""
        while not self._shutdown_event.is_set():
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Rollup scheduler tick failed: {e}", exc_info=True)
            
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                continue
    
    async def _tick(self):
        """Single scheduler tick - check if we should run generation."""
        if not settings.fast_rollup_generation_enabled:
            return
        
        now = datetime.now(timezone.utc)
        current_day = now.day
        current_hour = now.hour
        
        # Run if:
        # 1. It's the target hour (2 AM)
        # 2. We haven't run today yet
        should_run = (
            current_hour == self._target_hour and
            self._last_run_date != current_day
        )
        
        if should_run:
            logger.info(f"Triggering scheduled rollup generation at {now.isoformat()}")
            try:
                await self._run_generation()
                self._last_run_date = current_day
            except Exception as e:
                logger.error(f"Scheduled rollup generation failed: {e}, previous rollups remain available", exc_info=True)
        else:
            logger.debug(f"Scheduler tick: current_hour={current_hour}, "
                        f"target_hour={self._target_hour}, "
                        f"last_run_date={self._last_run_date}, "
                        f"current_day={current_day}")
    
    async def _run_generation(self):
        """Run rollup generation."""
        try:
            logger.info("Starting rollup generation")
            start_time = datetime.now()
            
            result = await self.generator.generate_all_rollups()
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(
                f"Rollup generation complete in {duration:.2f}s: "
                f"{result['daily_generated']} daily, "
                f"{result['weekly_generated']} weekly, "
                f"{result['monthly_generated']} monthly rollups for "
                f"{result['workgroups_processed']} workgroups"
            )
            
        except Exception as e:
            logger.error(f"Rollup generation failed: {e}", exc_info=True)
            raise
