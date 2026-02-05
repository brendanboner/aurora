"""Rollup generation service for fast pipeline.

Generates pre-computed summaries (rollups) for common query patterns:
- Daily rollups: Last 14 days of activity per workgroup
- Weekly rollups: Last 4 weeks of activity per workgroup

Rollups are stored in PostgreSQL and queried by fast pipeline templates.
"""

import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, select, and_, or_
from sqlalchemy.orm import sessionmaker, Session
import uuid

from src.models.db_models import Rollup
from src.services.keyword_retriever import get_repo
from src.settings import settings

logger = logging.getLogger(__name__)


class RollupGenerator:
    """Generates and manages rollup summaries for fast pipeline."""
    
    def __init__(self):
        """Initialize rollup generator with database connection."""
        self.engine = None
        self.SessionLocal = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Lazy initialization of database connection."""
        if self._initialized:
            return
        
        try:
            self.engine = create_engine(settings.postgres_dsn, echo=False)
            self.SessionLocal = sessionmaker(bind=self.engine)
            self._initialized = True
            logger.info("RollupGenerator initialized")
        except Exception as e:
            logger.error(f"Failed to initialize RollupGenerator: {e}")
            raise
    
    async def generate_all_rollups(self) -> Dict[str, int]:
        """
        Generate all rollups (daily, weekly, monthly) for active datasources.
        
        Includes both:
        - Workgroup-specific rollups (WFA Causeway workgroups)
        - Organization-level rollups (WFA Resource Center, WBA)
        
        ALL rollups are regenerated daily to keep queries fresh:
        - Daily rollups: Include today's activity
        - Weekly rollups: "This week" changes every day (Mon-today vs Fri-today)
        - Monthly rollups: "This month" includes progressively more days
        
        Returns:
            Dictionary with counts: {
                "daily_generated": int,
                "weekly_generated": int,
                "monthly_generated": int,
                "datasources_processed": int
            }
        """
        self._ensure_initialized()
        
        logger.info("Starting rollup generation for all datasources (daily, weekly, monthly)")
        
        try:
            # Get active datasources from Neo4j (workgroups + org-level sources)
            datasources = await self._get_active_datasources()
            logger.info(f"Found {len(datasources)} active datasources")
            
            daily_count = 0
            weekly_count = 0
            monthly_count = 0
            
            for ds in datasources:
                try:
                    # Generate daily rollups (last 14 days)
                    # Regenerated daily to include today
                    daily_count += await self._generate_daily_rollups(
                        ds["id"], 
                        ds["name"],
                        days_back=settings.fast_rollup_daily_lookback
                    )
                    
                    # Generate weekly rollups (last 4 weeks)
                    # Regenerated daily because "this week" changes every day
                    weekly_count += await self._generate_weekly_rollups(
                        ds["id"],
                        ds["name"],
                        weeks_back=settings.fast_rollup_weekly_lookback
                    )
                    
                    # Generate monthly rollups (last 3 months)
                    # Regenerated daily because "this month" grows daily
                    monthly_count += await self._generate_monthly_rollups(
                        ds["id"],
                        ds["name"],
                        months_back=settings.fast_rollup_monthly_lookback
                    )
                    
                except Exception as e:
                    logger.error(f"Failed to generate rollups for datasource {ds['name']}: {e}")
                    continue
            
            result = {
                "daily_generated": daily_count,
                "weekly_generated": weekly_count,
                "monthly_generated": monthly_count,
                "datasources_processed": len(datasources)
            }
            
            logger.info(f"Rollup generation complete: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Rollup generation failed: {e}", exc_info=True)
            raise
    
    async def _get_active_datasources(self) -> List[Dict[str, str]]:
        """
        Get list of active datasources from Neo4j.
        
        Includes:
        - Workgroups: DataSources with resource_url containing '/wg/' (WFA Causeway)
        - Org-level sources: WFA Resource Center, WBA Resources, etc.
        
        A datasource is considered active if it has had any activity in the last 90 days.
        """
        try:
            repo = get_repo()
            
            # Query for all DataSources with any documents
            # This includes both workgroups (/wg/) and org-level sources
            query = """
            MATCH (ds:DataSource)
            WHERE EXISTS {
                MATCH (ds)<-[:INGESTED_FROM]-(r:Resource)
            }
            RETURN DISTINCT ds.datasource_id as id, ds.name as name
            ORDER BY ds.name
            """
            
            result = repo.client.execute_query(query)
            datasources = [{"id": record["id"], "name": record["name"]} for record in result]
            
            return datasources
            
        except Exception as e:
            logger.error(f"Failed to fetch active datasources: {e}")
            return []
    
    async def _generate_daily_rollups(
        self, 
        workgroup_id: str, 
        workgroup_name: str, 
        days_back: int
    ) -> int:
        """
        Generate daily rollups for a workgroup.
        
        Regenerates each day to keep data fresh (today's activity).
        Deletes existing rollup before creating new one.
        """
        count = 0
        today = date.today()
        
        for days_ago in range(days_back):
            target_date = today - timedelta(days=days_ago)
            
            # Delete existing rollup if present (we're refreshing)
            self._delete_rollup_if_exists("day", target_date, target_date, workgroup_id)
            
            # Generate rollup for this day
            rollup = await self._create_daily_rollup(
                workgroup_id,
                workgroup_name,
                target_date
            )
            
            if rollup:
                self._save_rollup(rollup)
                count += 1
                logger.debug(f"Generated daily rollup for {workgroup_name} on {target_date}")
        
        return count
    
    async def _generate_weekly_rollups(
        self,
        workgroup_id: str,
        workgroup_name: str,
        weeks_back: int
    ) -> int:
        """
        Generate weekly rollups for a workgroup.
        
        Regenerates each day because "this week" changes daily:
        - Monday: includes Mon only
        - Friday: includes Mon-Fri
        Deletes existing before creating new.
        """
        count = 0
        today = date.today()
        
        for weeks_ago in range(weeks_back):
            # For current week (weeks_ago=0): Monday-today
            # For past weeks: full Monday-Sunday
            if weeks_ago == 0:
                # Current week: start of week (Monday) to today
                week_start = today - timedelta(days=today.weekday())
                week_end = today
            else:
                # Past weeks: full week Monday-Sunday
                week_start = today - timedelta(weeks=weeks_ago, days=today.weekday())
                week_end = week_start + timedelta(days=6)
            
            # Don't generate for future weeks
            if week_start > today:
                continue
            
            # Delete existing rollup if present (we're refreshing)
            self._delete_rollup_if_exists("week", week_start, week_end, workgroup_id)
            
            # Generate rollup for this week
            rollup = await self._create_weekly_rollup(
                workgroup_id,
                workgroup_name,
                week_start,
                week_end
            )
            
            if rollup:
                self._save_rollup(rollup)
                count += 1
                logger.debug(f"Generated weekly rollup for {workgroup_name} week {week_start}-{week_end}")
        
        return count
    
    async def _generate_monthly_rollups(
        self,
        workgroup_id: str,
        workgroup_name: str,
        months_back: int
    ) -> int:
        """
        Generate monthly rollups for a workgroup.
        
        Regenerates each day because \"this month\" grows daily:
        - Jan 5: includes Jan 1-5
        - Jan 25: includes Jan 1-25
        Deletes existing before creating new.
        """
        count = 0
        today = date.today()
        
        for months_ago in range(months_back):
            # For current month (months_ago=0): first of month to today
            # For past months: full month
            if months_ago == 0:
                # Current month: first day to today
                month_start = today.replace(day=1)
                month_end = today
            else:
                # Past months: full month
                target_month = today - timedelta(days=30 * months_ago)
                month_start = target_month.replace(day=1)
                # Last day of month
                if month_start.month == 12:
                    month_end = month_start.replace(day=31)
                else:
                    next_month = month_start.replace(month=month_start.month + 1, day=1)
                    month_end = next_month - timedelta(days=1)
            
            # Don't generate for future months
            if month_start > today:
                continue
            
            # Delete existing rollup if present (we're refreshing)
            self._delete_rollup_if_exists("month", month_start, month_end, workgroup_id)
            
            # Generate rollup for this month
            rollup = await self._create_monthly_rollup(
                workgroup_id,
                workgroup_name,
                month_start,
                month_end
            )
            
            if rollup:
                self._save_rollup(rollup)
                count += 1
                logger.debug(f"Generated monthly rollup for {workgroup_name} month {month_start}-{month_end}")
        
        return count
    
    async def _create_daily_rollup(
        self,
        workgroup_id: str,
        workgroup_name: str,
        target_date: date
    ) -> Optional[Rollup]:
        """Create a daily rollup for a specific date."""
        try:
            repo = get_repo()
            
            # Query Neo4j for day's activity from this DataSource
            # Intelligent date handling:
            # - Events: Use startTime (when event actually happens)
            # - Resources: Use publish_date (when document was published)
            #              OR INGESTED_IN.created_at (when we scraped it) as fallback
            query = """
            MATCH (ds:DataSource {datasource_id: $workgroup_id})
            
            // Get meeting events on this day (by event start_date)
            OPTIONAL MATCH (ds)<-[:INGESTED_FROM]-(e:Event)
            WHERE e.event_type = 'meeting'
              AND e.start_date IS NOT NULL
              AND e.start_date >= localdatetime($target_date)
              AND e.start_date < localdatetime($target_date) + duration('P1D')
            
            // Get documents by publish_date (preferred) or ingestion date (fallback)
            OPTIONAL MATCH (ds)<-[:INGESTED_FROM]-(r:Resource)
            OPTIONAL MATCH (r)-[:INGESTED_IN]->(batch:IngestionBatch)
            WHERE (r.publish_date IS NOT NULL 
                   AND r.publish_date >= localdatetime($target_date)
                   AND r.publish_date < localdatetime($target_date) + duration('P1D'))
               OR (r.publish_date IS NULL AND batch.created_at IS NOT NULL 
                   AND batch.created_at >= localdatetime($target_date)
                   AND batch.created_at < localdatetime($target_date) + duration('P1D'))
            
            // Get top topics from these documents
            OPTIONAL MATCH (r)-[rt:RELATES_TO]->(t:Topic)
            WHERE rt.relevance >= 0.5
            
            WITH ds, 
                 collect(DISTINCT e)[..10] as events,
                 collect(DISTINCT r)[..20] as docs,
                 collect(DISTINCT t.name)[..10] as topics
            
            RETURN 
                size(events) as event_count,
                size(docs) as doc_count,
                [event IN events | {id: event.url_hash, name: event.name, url: event.url, start_date: event.start_date}] as events,
                [doc IN docs | {id: doc.url_hash, title: doc.title, url: doc.url, category: doc.category, publish_date: doc.publish_date}] as docs,
                topics
            """
            
            result = repo.client.execute_query(query, {
                "workgroup_id": workgroup_id,
                "target_date": target_date.strftime("%Y-%m-%d")
            })
            
            if not result:
                return None
            
            record = result[0]
            event_count = record["event_count"]
            doc_count = record["doc_count"]
            
            # Skip if no activity
            if event_count == 0 and doc_count == 0:
                logger.debug(f"No activity for {workgroup_name} on {target_date}")
                return None
            
            # Generate summary
            summary = self._generate_summary(
                workgroup_name,
                target_date,
                target_date,
                record["events"],
                record["docs"],
                "day"
            )
            
            # Extract key events and decisions
            key_events = [e["name"] for e in record["events"][:5]]
            key_decisions = [
                {"title": d["title"], "url": d["url"]}
                for d in record["docs"]
                if d["category"] and "decision" in d["category"].lower()
            ][:5]
            
            # Build links list
            links = []
            for e in record["events"][:5]:
                if e["url"]:
                    links.append({"title": e["name"], "url": e["url"]})
            for d in record["docs"][:5]:
                if d["url"]:
                    links.append({"title": d["title"], "url": d["url"]})
            
            # Create rollup
            rollup = Rollup(
                id=uuid.uuid4(),
                rollup_type="day",
                start_date=datetime.combine(target_date, datetime.min.time()),
                end_date=datetime.combine(target_date, datetime.max.time()),
                workgroup_id=workgroup_id,
                workgroup_name=workgroup_name,
                summary=summary,
                key_events=key_events,
                key_decisions=key_decisions,
                top_topics=record["topics"][:10],
                links=links,
                event_count=event_count,
                document_count=doc_count,
                generated_at=datetime.utcnow(),
                generation_method="autonomous",
                template_version=settings.fast_template_version
            )
            
            return rollup
            
        except Exception as e:
            logger.error(f"Failed to create daily rollup for {workgroup_name} on {target_date}: {e}")
            return None
    
    async def _create_weekly_rollup(
        self,
        workgroup_id: str,
        workgroup_name: str,
        week_start: date,
        week_end: date
    ) -> Optional[Rollup]:
        """Create a weekly rollup for a specific week."""
        try:
            repo = get_repo()
            
            # Query Neo4j for week's activity from this DataSource (workgroup)
            # Intelligent date handling:
            # - Events: Use startTime (when event happens)
            # - Resources: Use publish_date OR ingestion date as fallback
            query = """
            MATCH (ds:DataSource {datasource_id: $workgroup_id})
            
            // Get workgroup meeting events in this week (by event start_date)
            OPTIONAL MATCH (ds)<-[:INGESTED_FROM]-(e:Event)
            WHERE e.event_type = 'meeting'
              AND e.start_date IS NOT NULL
              AND e.start_date >= localdatetime($week_start)
              AND e.start_date < localdatetime($week_end) + duration('P1D')
            
            // Get documents by publish_date (preferred) or ingestion date (fallback)
            OPTIONAL MATCH (ds)<-[:INGESTED_FROM]-(r:Resource)
            OPTIONAL MATCH (r)-[:INGESTED_IN]->(batch:IngestionBatch)
            WHERE (r.publish_date IS NOT NULL 
                   AND r.publish_date >= localdatetime($week_start)
                   AND r.publish_date < localdatetime($week_end) + duration('P1D'))
               OR (r.publish_date IS NULL AND batch.created_at IS NOT NULL
                   AND batch.created_at >= localdatetime($week_start)
                   AND batch.created_at < localdatetime($week_end) + duration('P1D'))
            
            // Get top topics from these documents
            OPTIONAL MATCH (r)-[rt:RELATES_TO]->(t:Topic)
            WHERE rt.relevance >= 0.5
            
            WITH ds,
                 collect(DISTINCT e)[..20] as events,
                 collect(DISTINCT r)[..50] as docs,
                 collect(DISTINCT t.name)[..15] as topics
            
            RETURN 
                size(events) as event_count,
                size(docs) as doc_count,
                [event IN events | {id: event.url_hash, name: event.name, url: event.url, start_date: event.start_date}] as events,
                [doc IN docs | {id: doc.url_hash, title: doc.title, url: doc.url, category: doc.category, publish_date: doc.publish_date}] as docs,
                topics
            """
            
            result = repo.client.execute_query(query, {
                "workgroup_id": workgroup_id,
                "week_start": week_start.strftime("%Y-%m-%d"),
                "week_end": week_end.strftime("%Y-%m-%d")
            })
            
            if not result:
                return None
            
            record = result[0]
            event_count = record["event_count"]
            doc_count = record["doc_count"]
            
            # Skip if no activity
            if event_count == 0 and doc_count == 0:
                logger.debug(f"No activity for {workgroup_name} week {week_start}-{week_end}")
                return None
            
            # Generate summary
            summary = self._generate_summary(
                workgroup_name,
                week_start,
                week_end,
                record["events"],
                record["docs"],
                "week"
            )
            
            # Extract key events and decisions
            key_events = [e["name"] for e in record["events"][:10]]
            key_decisions = [
                {"title": d["title"], "url": d["url"]}
                for d in record["docs"]
                if d["category"] and "decision" in d["category"].lower()
            ][:10]
            
            # Build links list
            links = []
            for e in record["events"][:10]:
                if e["url"]:
                    links.append({"title": e["name"], "url": e["url"]})
            for d in record["docs"][:10]:
                if d["url"]:
                    links.append({"title": d["title"], "url": d["url"]})
            
            # Create rollup
            rollup = Rollup(
                id=uuid.uuid4(),
                rollup_type="week",
                start_date=datetime.combine(week_start, datetime.min.time()),
                end_date=datetime.combine(week_end, datetime.max.time()),
                workgroup_id=workgroup_id,
                workgroup_name=workgroup_name,
                summary=summary,
                key_events=key_events,
                key_decisions=key_decisions,
                top_topics=record["topics"][:15],
                links=links,
                event_count=event_count,
                document_count=doc_count,
                generated_at=datetime.utcnow(),
                generation_method="autonomous",
                template_version=settings.fast_template_version
            )
            
            return rollup
            
        except Exception as e:
            logger.error(f"Failed to create weekly rollup for {workgroup_name} week {week_start}-{week_end}: {e}")
            return None
    
    async def _create_monthly_rollup(
        self,
        workgroup_id: str,
        workgroup_name: str,
        month_start: date,
        month_end: date
    ) -> Optional[Rollup]:
        """Create a monthly rollup for a specific month."""
        try:
            repo = get_repo()
            
            # Query Neo4j for month's activity from this DataSource (workgroup)
            # Intelligent date handling:
            # - Events: Use startTime (when event happens)
            # - Resources: Use publish_date OR ingestion date as fallback
            query = """
            MATCH (ds:DataSource {datasource_id: $workgroup_id})
            
            // Get workgroup meeting events in this month (by event start_date)
            OPTIONAL MATCH (ds)<-[:INGESTED_FROM]-(e:Event)
            WHERE e.event_type = 'meeting'
              AND e.start_date IS NOT NULL
              AND e.start_date >= localdatetime($month_start)
              AND e.start_date < localdatetime($month_end) + duration('P1D')
            
            // Get documents by publish_date (preferred) or ingestion date (fallback)
            OPTIONAL MATCH (ds)<-[:INGESTED_FROM]-(r:Resource)
            OPTIONAL MATCH (r)-[:INGESTED_IN]->(batch:IngestionBatch)
            WHERE (r.publish_date IS NOT NULL
                   AND r.publish_date >= localdatetime($month_start)
                   AND r.publish_date < localdatetime($month_end) + duration('P1D'))
               OR (r.publish_date IS NULL AND batch.created_at IS NOT NULL
                   AND batch.created_at >= localdatetime($month_start)
                   AND batch.created_at < localdatetime($month_end) + duration('P1D'))
            
            // Get top topics from these documents
            OPTIONAL MATCH (r)-[rt:RELATES_TO]->(t:Topic)
            WHERE rt.relevance >= 0.5
            
            WITH ds,
                 collect(DISTINCT e)[..30] as events,
                 collect(DISTINCT r)[..100] as docs,
                 collect(DISTINCT t.name)[..20] as topics
            
            RETURN 
                size(events) as event_count,
                size(docs) as doc_count,
                [event IN events | {id: event.url_hash, name: event.name, url: event.url, start_date: event.start_date}] as events,
                [doc IN docs | {id: doc.url_hash, title: doc.title, url: doc.url, category: doc.category, publish_date: doc.publish_date}] as docs,
                topics
            """
            
            result = repo.client.execute_query(query, {
                "workgroup_id": workgroup_id,
                "month_start": month_start.strftime("%Y-%m-%d"),
                "month_end": month_end.strftime("%Y-%m-%d")
            })
            
            if not result:
                return None
            
            record = result[0]
            event_count = record["event_count"]
            doc_count = record["doc_count"]
            
            # Skip if no activity
            if event_count == 0 and doc_count == 0:
                logger.debug(f"No activity for {workgroup_name} month {month_start}-{month_end}")
                return None
            
            # Generate summary
            summary = self._generate_summary(
                workgroup_name,
                month_start,
                month_end,
                record["events"],
                record["docs"],
                "month"
            )
            
            # Extract key events and decisions
            key_events = [e["name"] for e in record["events"][:15]]
            key_decisions = [
                {"title": d["title"], "url": d["url"]}
                for d in record["docs"]
                if d["category"] and "decision" in d["category"].lower()
            ][:15]
            
            # Build links list
            links = []
            for e in record["events"][:15]:
                if e["url"]:
                    links.append({"title": e["name"], "url": e["url"]})
            for d in record["docs"][:15]:
                if d["url"]:
                    links.append({"title": d["title"], "url": d["url"]})
            
            # Create rollup
            rollup = Rollup(
                id=uuid.uuid4(),
                rollup_type="month",
                start_date=datetime.combine(month_start, datetime.min.time()),
                end_date=datetime.combine(month_end, datetime.max.time()),
                workgroup_id=workgroup_id,
                workgroup_name=workgroup_name,
                summary=summary,
                key_events=key_events,
                key_decisions=key_decisions,
                top_topics=record["topics"][:20],
                links=links,
                event_count=event_count,
                document_count=doc_count,
                generated_at=datetime.utcnow(),
                generation_method="autonomous",
                template_version=settings.fast_template_version
            )
            
            return rollup
            
        except Exception as e:
            logger.error(f"Failed to create monthly rollup for {workgroup_name} month {month_start}-{month_end}: {e}")
            return None
    
    def _generate_summary(
        self,
        workgroup_name: str,
        start_date: date,
        end_date: date,
        events: List[Dict],
        docs: List[Dict],
        period_type: str
    ) -> str:
        """Generate a human-readable summary from structured data."""
        period_desc = f"{start_date.strftime('%B %d, %Y')}" if period_type == "day" else \
                      f"{start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"
        
        event_count = len(events)
        doc_count = len(docs)
        
        # Count decision documents
        decision_count = sum(1 for d in docs if d.get("category") and "decision" in d["category"].lower())
        
        # Build summary
        summary_parts = [f"{workgroup_name} activity for {period_desc}:"]
        
        if event_count > 0:
            summary_parts.append(f"{event_count} event(s)")
        if doc_count > 0:
            summary_parts.append(f"{doc_count} document(s)")
        if decision_count > 0:
            summary_parts.append(f"including {decision_count} decision(s)")
        
        if event_count == 0 and doc_count == 0:
            summary_parts.append("No activity recorded")
        
        # Add top events
        if events:
            event_names = [e["name"] for e in events[:3]]
            summary_parts.append(f"Key events: {', '.join(event_names)}")
        
        return ". ".join(summary_parts) + "."
    
    def _rollup_exists(
        self,
        rollup_type: str,
        start_date: date,
        end_date: date,
        workgroup_id: str
    ) -> bool:
        """Check if a rollup already exists."""
        try:
            session = self.SessionLocal()
            
            start_dt = datetime.combine(start_date, datetime.min.time())
            end_dt = datetime.combine(end_date, datetime.max.time())
            
            exists = session.query(Rollup).filter(
                and_(
                    Rollup.rollup_type == rollup_type,
                    Rollup.start_date == start_dt,
                    Rollup.end_date == end_dt,
                    Rollup.workgroup_id == workgroup_id
                )
            ).first() is not None
            
            session.close()
            return exists
            
        except Exception as e:
            logger.error(f"Failed to check rollup existence: {e}")
            return False
    
    def _delete_rollup_if_exists(
        self,
        rollup_type: str,
        start_date: date,
        end_date: date,
        workgroup_id: str
    ):
        """Delete existing rollup to allow refresh."""
        session = None
        try:
            session = self.SessionLocal()
            
            start_dt = datetime.combine(start_date, datetime.min.time())
            end_dt = datetime.combine(end_date, datetime.max.time())
            
            deleted = session.query(Rollup).filter(
                and_(
                    Rollup.rollup_type == rollup_type,
                    Rollup.start_date == start_dt,
                    Rollup.end_date == end_dt,
                    Rollup.workgroup_id == workgroup_id
                )
            ).delete()
            
            session.commit()
            
            if deleted > 0:
                logger.debug(f"Deleted existing {rollup_type} rollup for refresh")
            
        except Exception as e:
            logger.error(f"Failed to delete rollup: {e}")
            if session:
                session.rollback()
        finally:
            if session:
                session.close()
    
    def _save_rollup(self, rollup: Rollup):
        """Save rollup to database, updating if already exists."""
        session = self.SessionLocal()
        try:
            # Try to find existing rollup with same key
            existing = session.query(Rollup).filter(
                and_(
                    Rollup.rollup_type == rollup.rollup_type,
                    Rollup.start_date == rollup.start_date,
                    Rollup.workgroup_id == rollup.workgroup_id
                )
            ).first()
            
            if existing:
                # Update existing rollup
                existing.end_date = rollup.end_date
                existing.workgroup_name = rollup.workgroup_name
                existing.summary = rollup.summary
                existing.key_events = rollup.key_events
                existing.key_decisions = rollup.key_decisions
                existing.top_topics = rollup.top_topics
                existing.links = rollup.links
                existing.event_count = rollup.event_count
                existing.document_count = rollup.document_count
                existing.generated_at = rollup.generated_at
                existing.generation_method = rollup.generation_method
                existing.template_version = rollup.template_version
                logger.debug(f"Updated rollup: {rollup.rollup_type} for {rollup.workgroup_name} {rollup.start_date.date()}")
            else:
                # Insert new rollup
                session.add(rollup)
                logger.debug(f"Saved rollup: {rollup.rollup_type} for {rollup.workgroup_name} {rollup.start_date.date()}")
            
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save rollup: {e}")
            raise
        finally:
            session.close()
    
    def query_rollups(
        self,
        rollup_type: str,
        workgroup_ids: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Query rollups from PostgreSQL.
        
        Args:
            rollup_type: Type of rollup ('day', 'week', 'month')
            workgroup_ids: Filter by workgroup IDs (datasource_ids)
            start_date: Filter rollups that overlap with this date or later
            end_date: Filter rollups that overlap with this date or earlier
            limit: Maximum number of rollups to return
            
        Returns:
            List of rollup dictionaries
        """
        self._ensure_initialized()
        session = self.SessionLocal()
        
        try:
            query = session.query(Rollup).filter(Rollup.rollup_type == rollup_type)
            
            # Filter by workgroup IDs
            if workgroup_ids:
                query = query.filter(Rollup.workgroup_id.in_(workgroup_ids))
            
            # Filter by date range (rollups that overlap with requested range)
            if start_date:
                # Rollup end_date >= start_date (rollup extends into or past our start)
                query = query.filter(Rollup.end_date >= datetime.combine(start_date, datetime.min.time()))
            
            if end_date:
                # Rollup start_date <= end_date (rollup begins before or at our end)
                query = query.filter(Rollup.start_date <= datetime.combine(end_date, datetime.max.time()))
            
            # Order by most recent first
            query = query.order_by(Rollup.start_date.desc())
            
            # Apply limit
            query = query.limit(limit)
            
            rollups = query.all()
            
            # Convert to dictionaries for compatibility with Neo4j result format
            results = []
            for r in rollups:
                results.append({
                    "rollup_id": str(r.id),
                    "rollup_type": r.rollup_type,
                    "rollup_summary": r.summary,
                    "key_events": r.key_events or [],
                    "key_decisions": r.key_decisions or [],
                    "top_topics": r.top_topics or [],
                    "links": r.links or [],
                    "rollup_start": r.start_date.isoformat() if r.start_date else None,
                    "rollup_end": r.end_date.isoformat() if r.end_date else None,
                    "workgroup_id": r.workgroup_id,
                    "workgroup_name": r.workgroup_name,
                    "event_count": r.event_count,
                    "document_count": r.document_count,
                    "generated_at": r.generated_at.isoformat() if r.generated_at else None,
                    "source_type": "rollup"
                })
            
            logger.info(f"Retrieved {len(results)} {rollup_type} rollups from PostgreSQL")
            return results
            
        except Exception as e:
            logger.error(f"Failed to query rollups: {e}")
            return []
        finally:
            session.close()
