"""
Knowledge Graph Curator Service

Long-running service that orchestrates:
1. Event reconciliation (continuous, interval-based)
2. Topic hierarchy organization (scheduled, cron-based + threshold-based)

Provides API endpoints for health checks and manual triggers.
"""

import sys
import signal
import threading
import time
from datetime import datetime
from typing import Optional

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from settings import settings
from utils.logger import setup_logger
from api import app, set_scheduler, set_start_time, update_job_state
from services.topic_organizer import TopicOrganizer
from services.event_reconciler import EventReconciler
from services.threshold_monitor import TopicThresholdMonitor
from services.importance_decay import ImportanceDecayService
from services.orphan_monitor import OrphanMonitorService
from services.date_repair import DateRepairService

logger = setup_logger(__name__, settings.log_level)


class CuratorScheduler:
    """
    Main scheduler for curator tasks.
    
    Manages APScheduler background jobs and integrates with FastAPI.
    """
    
    def __init__(self):
        """Initialize the scheduler."""
        self.scheduler: Optional[BackgroundScheduler] = None
        self._shutdown_event = threading.Event()
        self._start_time = datetime.now()
        self._threshold_monitor: Optional[TopicThresholdMonitor] = None
        self._event_reconciler: Optional[EventReconciler] = None
        self._importance_decay: Optional[ImportanceDecayService] = None
        self._orphan_monitor: Optional[OrphanMonitorService] = None
        self._date_repair: Optional[DateRepairService] = None
        
    def _run_topic_organization(self, triggered_by: str = "scheduled"):
        """Execute topic organization job.
        
        Args:
            triggered_by: Description of what triggered this run
        """
        job_name = "topic_organization"
        
        # Capture the start time BEFORE organization runs.
        # This ensures any topics created during organization will be counted
        # as "new" for the next threshold check. If we captured the timestamp
        # at the end, topics created during a long-running organization would
        # be missed (their created_at < end_timestamp).
        organization_start_time = datetime.now()
        
        try:
            update_job_state(job_name, is_running=True)
            
            # Set running flag in Redis (for threshold monitor)
            if self._threshold_monitor:
                self._threshold_monitor.set_curation_running(True)
            
            logger.info("=" * 60)
            logger.info(f"Starting topic organization (triggered by: {triggered_by})")
            logger.info("=" * 60)
            
            # Create heartbeat callback to extend Redis lock during long runs
            heartbeat_cb = None
            if self._threshold_monitor:
                heartbeat_cb = self._threshold_monitor.extend_curation_lock
            
            organizer = TopicOrganizer(
                heartbeat_callback=heartbeat_cb,
                logger_instance=logger
            )
            result = organizer.run()
            
            # Log summary if available
            if result and isinstance(result, dict):
                logger.info(
                    f"Topic organization stats: "
                    f"{result.get('clusters_created', 0)} clusters, "
                    f"{result.get('relationships_created', 0)} relationships"
                )
            
            # Update last curation timestamp using the START time we captured.
            # This ensures topics created during organization will be counted next time.
            if self._threshold_monitor:
                self._threshold_monitor.set_last_curation_timestamp(organization_start_time)
                self._threshold_monitor.set_curation_running(False)
            
            update_job_state(
                job_name,
                is_running=False,
                last_run=datetime.now(),
                last_error=None,
            )
            logger.info("Topic organization completed successfully")
            
            # Immediately check if another organization is needed
            # (topics may have been created during the run)
            self._schedule_immediate_recheck()
            
        except Exception as e:
            logger.error(f"Topic organization failed: {e}", exc_info=True)
            
            # Clear running flag on error
            if self._threshold_monitor:
                self._threshold_monitor.set_curation_running(False)
            
            update_job_state(
                job_name,
                is_running=False,
                last_error=str(e),
            )
    
    def _run_event_reconciliation(self):
        """Execute event reconciliation job."""
        job_name = "event_reconciliation"
        
        try:
            update_job_state(job_name, is_running=True)
            logger.info("-" * 40)
            logger.info("Starting event reconciliation")
            logger.info("-" * 40)
            
            # Use persistent reconciler
            if not self._event_reconciler:
                logger.warning("Event reconciler not initialized, skipping")
                return
            
            result = self._event_reconciler.run()
            
            # Log summary if available
            if result and isinstance(result, dict):
                stats = []
                if result.get('batches_processed', 0) > 0:
                    stats.append(f"{result['batches_processed']} batches")
                if result.get('marked_unconfirmed', 0) > 0:
                    stats.append(f"{result['marked_unconfirmed']} unconfirmed")
                if result.get('supersedes_created', 0) > 0:
                    stats.append(f"{result['supersedes_created']} supersedes")
                if result.get('auto_cancelled', 0) > 0:
                    stats.append(f"{result['auto_cancelled']} auto-cancelled")
                if stats:
                    logger.info(f"Event reconciliation stats: {', '.join(stats)}")
            
            update_job_state(
                job_name,
                is_running=False,
                last_run=datetime.now(),
                last_error=None,
            )
            logger.info("Event reconciliation completed")
            
        except Exception as e:
            logger.error(f"Event reconciliation failed: {e}", exc_info=True)
            update_job_state(
                job_name,
                is_running=False,
                last_error=str(e),
            )
    
    def _check_event_reconciliation(self):
        """Check if there are completed batches pending reconciliation."""
        if not self._event_reconciler:
            return
            
        try:
            logger.debug("Checking for batches pending reconciliation...")
            
            has_work, pending_count = self._event_reconciler.has_pending_work()
            
            if has_work:
                logger.info(
                    f"Event reconciliation triggered: {pending_count} completed batch(es) pending"
                )
                self._run_event_reconciliation()
            else:
                logger.debug("No batches pending reconciliation")
                
        except Exception as e:
            logger.error(f"Error checking event reconciliation: {e}", exc_info=True)
    
    def _check_topic_threshold(self):
        """Check if topic threshold is met and trigger organization if needed."""
        if not self._threshold_monitor:
            return
        try:
            logger.debug("Checking topic threshold...")
            
            should_trigger, new_count, reason = self._threshold_monitor.should_trigger_curation()
            
            if should_trigger:
                logger.info(
                    f"Topic organization triggered: {reason}"
                )
                # Run topic organization with trigger context
                self._run_topic_organization(triggered_by=reason)
            elif new_count > 0:
                logger.debug(
                    f"Topic threshold not met: {new_count}/{settings.topic_threshold_count} new topics"
                )
            else:
                logger.debug("No new topics since last curation")
                
        except Exception as e:
            logger.error(f"Error checking topic threshold: {e}", exc_info=True)
    
    def _run_importance_decay(self):
        """Execute daily importance-decay refresh job."""
        job_name = "importance_decay"
        try:
            update_job_state(job_name, is_running=True)
            logger.info("-" * 40)
            logger.info("Starting importance decay refresh")
            if self._importance_decay is None:
                self._importance_decay = ImportanceDecayService()
            summary = self._importance_decay.run()
            update_job_state(
                job_name,
                is_running=False,
                last_run=datetime.now(),
                last_error=None,
            )
            logger.info(f"Importance decay complete: {summary}")
        except Exception as e:
            logger.error(f"Importance decay failed: {e}", exc_info=True)
            update_job_state(job_name, is_running=False, last_error=str(e))

    def _run_date_repair(self):
        """Execute daily publish_date back-fill job (runs at 04:00 UTC)."""
        job_name = "date_repair"
        try:
            update_job_state(job_name, is_running=True)
            logger.info("-" * 40)
            logger.info("Starting publish_date repair job")
            if self._date_repair is None:
                self._date_repair = DateRepairService()
            summary = self._date_repair.run()
            update_job_state(
                job_name,
                is_running=False,
                last_run=datetime.now(),
                last_error=None,
            )
            logger.info(
                f"Date repair complete: {summary.get('total_repaired', 0)} resources patched"
            )
        except Exception as e:
            logger.error(f"Date repair failed: {e}", exc_info=True)
            update_job_state(job_name, is_running=False, last_error=str(e))

    def _run_orphan_monitor(self):
        """Execute periodic orphan-resource monitoring job."""
        job_name = "orphan_monitor"
        try:
            update_job_state(job_name, is_running=True)
            if self._orphan_monitor is None:
                self._orphan_monitor = OrphanMonitorService()
            summary = self._orphan_monitor.run()
            update_job_state(
                job_name,
                is_running=False,
                last_run=datetime.now(),
                last_error=None,
            )
            if summary.get("orphan_count", 0) > 0:
                logger.warning(
                    f"Orphan monitor: {summary['orphan_count']} orphaned resource(s) — "
                    f"review digester logs or re-queue for processing"
                )
        except Exception as e:
            logger.error(f"Orphan monitor failed: {e}", exc_info=True)
            update_job_state(job_name, is_running=False, last_error=str(e))

    def _run_stalled_batch_cleanup(self):
        """Mark stalled IngestionBatch nodes as failed.

        Runs every 30 minutes. A batch is stalled when it has been in
        'retrieving' or 'digesting' status for more than 2 hours — this means
        the scraper or digester hung or was restarted mid-run.

        This is the background companion to the digester's startup cleanup:
        - Digester startup handles the common 'restart mid-run' case instantly.
        - This watchdog catches the rarer 'process hung without restarting' case.
        """
        from neo4j_client.client import Neo4jClient

        job_name = "stalled_batch_cleanup"
        stall_hours = 2
        try:
            update_job_state(job_name, is_running=True)
            client = Neo4jClient(
                uri=settings.neo4j_uri, user=settings.neo4j_user,
                password=settings.neo4j_password, database=settings.neo4j_database
            )
            client.connect()
            result = client.execute_write(
                f"""
                MATCH (b:IngestionBatch)
                WHERE b.status IN ['retrieving', 'digesting', 'scraping']
                  AND b.scrape_started_at < datetime() - duration('PT{stall_hours}H')
                SET b.status        = 'failed',
                    b.error_message = 'Auto-cleaned by curator watchdog: stuck in '
                                      + b.status + ' for >{stall_hours}h',
                    b.digest_completed_at = datetime()
                RETURN count(b) AS fixed
                """,
                {},
            )
            client.close()
            fixed = result[0]["fixed"] if result else 0
            update_job_state(job_name, is_running=False, last_run=datetime.now(), last_error=None)
            if fixed > 0:
                logger.warning(
                    f"Stalled batch watchdog: marked {fixed} batch(es) as failed "
                    f"(stuck >{stall_hours}h in retrieving/digesting)"
                )
            else:
                logger.debug("Stalled batch watchdog: no stalled batches found")
        except Exception as exc:
            logger.error(f"Stalled batch cleanup failed: {exc}", exc_info=True)
            update_job_state(job_name, is_running=False, last_error=str(exc))

    def _schedule_immediate_recheck(self):
        """
        Schedule an immediate threshold check after organization completes.
        
        Topics may have been created during the organization run. This ensures
        they are processed promptly rather than waiting for the next scheduled check.
        """
        if not self._threshold_monitor:
            return
        
        try:
            # Small delay to allow any in-flight topic creations to complete
            logger.info("Scheduling immediate threshold re-check in 5 seconds...")
            
            def delayed_check():
                time.sleep(5)
                if not self._shutdown_event.is_set():
                    self._check_topic_threshold()
            
            threading.Thread(target=delayed_check, daemon=True).start()
            
        except Exception as e:
            logger.warning(f"Failed to schedule immediate recheck: {e}")
    
    def setup_scheduler(self):
        """Configure and start the APScheduler."""
        logger.info("Setting up APScheduler...")
        
        self.scheduler = BackgroundScheduler(
            job_defaults={
                'coalesce': True,  # Combine missed runs into single run
                'max_instances': 1,  # Only one instance of each job at a time
                'misfire_grace_time': 60 * 30,  # 30 min grace period for missed jobs
            }
        )
        
        # Schedule topic organization
        # If threshold monitoring is enabled, it handles triggering based on new topics
        # If disabled, fall back to cron-based scheduling
        if settings.topic_threshold_enabled:
            # Initialize threshold monitor
            self._threshold_monitor = TopicThresholdMonitor()
            
            self.scheduler.add_job(
                self._check_topic_threshold,
                trigger=IntervalTrigger(
                    seconds=settings.topic_threshold_check_interval_seconds
                ),
                id="topic_threshold_check",
                name="Topic Threshold Check",
                replace_existing=True,
            )
            logger.info(
                f"Topic organization: threshold-based (check every "
                f"{settings.topic_threshold_check_interval_seconds}s, "
                f"trigger at {settings.topic_threshold_count} new topics)"
            )
        else:
            # Fallback: cron-based scheduling when threshold monitoring is disabled
            cron_parts = settings.topic_organization_cron.split()
            if len(cron_parts) >= 5:
                cron_trigger = CronTrigger(
                    minute=cron_parts[0],
                    hour=cron_parts[1],
                    day=cron_parts[2],
                    month=cron_parts[3],
                    day_of_week=cron_parts[4],
                )
            else:
                logger.warning(
                    f"Invalid cron expression: {settings.topic_organization_cron}. "
                    f"Using default: daily at 6 AM"
                )
                cron_trigger = CronTrigger(hour=6, minute=0)
            
            self.scheduler.add_job(
                self._run_topic_organization,
                trigger=cron_trigger,
                id="topic_organization",
                name="Topic Hierarchy Organization",
                replace_existing=True,
            )
            logger.info(
                f"Topic organization: cron-based ({settings.topic_organization_cron})"
            )
        
        # Schedule event reconciliation check (interval-based)
        # Checks Redis for pending scrape:complete:* signals
        if settings.event_reconciliation_enabled:
            # Initialize persistent event reconciler
            self._event_reconciler = EventReconciler(logger_instance=logger)
            
            self.scheduler.add_job(
                self._check_event_reconciliation,
                trigger=IntervalTrigger(
                    seconds=settings.event_reconciliation_check_interval_seconds
                ),
                id="event_reconciliation_check",
                name="Event Reconciliation Check",
                replace_existing=True,
            )
            logger.info(
                f"Event reconciliation: check every "
                f"{settings.event_reconciliation_check_interval_seconds}s"
            )

        # Schedule importance decay (daily at 03:00)
        self.scheduler.add_job(
            self._run_importance_decay,
            trigger=CronTrigger(hour=3, minute=0),
            id="importance_decay",
            name="Importance Decay Refresh",
            replace_existing=True,
        )
        logger.info("Importance decay: scheduled daily at 03:00")

        # Schedule publish_date repair (daily at 04:00 — after importance decay)
        self.scheduler.add_job(
            self._run_date_repair,
            trigger=CronTrigger(hour=4, minute=0),
            id="date_repair",
            name="Publish Date Repair",
            replace_existing=True,
        )
        logger.info("Date repair: scheduled daily at 04:00")

        # Schedule orphan resource monitoring (every 6 hours)
        self.scheduler.add_job(
            self._run_orphan_monitor,
            trigger=IntervalTrigger(hours=6),
            id="orphan_monitor",
            name="Orphan Resource Monitor",
            replace_existing=True,
        )
        logger.info("Orphan monitor: scheduled every 6 hours")

        # Schedule stalled-batch watchdog (every 30 minutes).
        # Catches batches that get stuck without a service restart —
        # e.g., a scraper that hung on a network call and never returned.
        self.scheduler.add_job(
            self._run_stalled_batch_cleanup,
            trigger=IntervalTrigger(minutes=30),
            id="stalled_batch_cleanup",
            name="Stalled Batch Cleanup",
            replace_existing=True,
        )
        logger.info("Stalled batch watchdog: scheduled every 30 minutes")
        
        # Start the scheduler
        self.scheduler.start()
        logger.info("APScheduler started")
        
        # Log active jobs
        jobs = self.scheduler.get_jobs()
        logger.debug(f"Scheduled {len(jobs)} job(s): {[j.id for j in jobs]}")
        
        # Share scheduler with API
        set_scheduler(self.scheduler)
        set_start_time(self._start_time)
    
    def run_api(self):
        """Run the FastAPI server."""
        logger.info(f"Starting FastAPI server on port {settings.api_port}...")
        
        # Configure uvicorn to run without its own signal handlers
        # (we handle signals ourselves)
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=settings.api_port,
            log_level="info",
            access_log=True,
        )
        server = uvicorn.Server(config)
        
        # Run in a way that allows graceful shutdown
        server.run()
    
    def shutdown(self, signum=None, frame=None):
        """Gracefully shutdown the service."""
        logger.info("Shutting down curator service...")
        
        if self.scheduler:
            logger.info("Shutting down APScheduler...")
            # Wait for running jobs to complete (with 30 second timeout)
            # This prevents jobs from accessing closed resources during shutdown
            self.scheduler.shutdown(wait=True)
        
        if self._threshold_monitor:
            logger.info("Closing threshold monitor...")
            self._threshold_monitor.close()
        
        if self._event_reconciler:
            logger.info("Closing event reconciler...")
            self._event_reconciler.close()

        if self._importance_decay:
            logger.info("Closing importance decay service...")
            self._importance_decay.close()

        if self._orphan_monitor:
            logger.info("Closing orphan monitor...")
            self._orphan_monitor.close()

        if self._date_repair:
            logger.info("Closing date repair service...")
            self._date_repair.close()

        self._shutdown_event.set()
        logger.info("Shutdown complete")
        sys.exit(0)
    
    def run(self):
        """
        Main entry point - start scheduler and API server.
        """
        logger.info("=" * 60)
        logger.info("Starting Knowledge Graph Curator Service")
        logger.info("=" * 60)
        logger.info("Configuration:")
        if settings.topic_threshold_enabled:
            logger.info(f"  Topic organization: threshold-based")
            logger.info(f"    - Trigger after: {settings.topic_threshold_count} new topics")
            logger.info(f"    - Check interval: {settings.topic_threshold_check_interval_seconds}s")
        else:
            logger.info(f"  Topic organization: cron-based")
            logger.info(f"    - Schedule: {settings.topic_organization_cron}")
        if settings.event_reconciliation_enabled:
            logger.info(f"  Event reconciliation: signal-based")
            logger.info(f"    - Check interval: {settings.event_reconciliation_check_interval_seconds}s")
        else:
            logger.info(f"  Event reconciliation: disabled")
        logger.info("=" * 60)
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
        
        try:
            # Start the scheduler
            self.setup_scheduler()
            
            # Start API server (blocking call)
            self.run_api()
            
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            self.shutdown()


def main():
    """Main entry point."""
    curator = CuratorScheduler()
    curator.run()


if __name__ == "__main__":
    main()
