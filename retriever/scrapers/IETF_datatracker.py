"""
IETFDatatrackerScraper — fetches internet-drafts and meeting sessions from
the IETF Datatracker REST API for configured areas and working groups.

Configuration (from DataSource node `folders` field):
  folders: ["area:wit", "area:int", "area:sec", "wg:quic"]
  - "area:{acronym}" → scrape all active WGs within that IETF area
  - "wg:{acronym}"   → scrape just that specific WG

Per-WG resources are published with:
  datasource_id = "ietf_wg_{wg_acronym}"   (e.g. "ietf_wg_quic")
  workgroup_id  = wg_acronym                (set via additional_fields)

Events (meeting sessions) are published with the same datasource_id.
"""

import asyncio
import aiohttp
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from .base import BaseScraper, Resource, Event

logger = logging.getLogger(__name__)

DATATRACKER_BASE = "https://datatracker.ietf.org"
IETF_MEETING_BASE = "https://datatracker.ietf.org/meeting"


class IETFDatatrackerScraper(BaseScraper):
    """
    Scraper for the IETF Datatracker.  Fetches:
      1. Active internet-drafts and recent RFC updates per working group.
      2. Meeting sessions (IETF plenaries + interim meetings) per WG,
         including linked slide and agenda materials.

    The `folders` config field drives which areas/WGs are scraped.
    """

    scraper_name = "ietf_datatracker"
    API_BASE = f"{DATATRACKER_BASE}/api/v1"

    def __init__(self):
        super().__init__()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _api_get(self, path: str, params: Dict[str, Any] = None) -> Optional[Dict]:
        """GET a Datatracker API endpoint and return parsed JSON, or None."""
        url = f"{self.API_BASE}{path}"
        try:
            async with self.session.get(
                url,
                params={**(params or {}), "format": "json"},
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"Accept": "application/json"},
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"HTTP {resp.status} for {url}")
                    return None
                return await resp.json()
        except Exception as exc:
            logger.error(f"Error calling {url}: {exc}")
            return None

    async def _paginated_get(
        self, path: str, params: Dict[str, Any] = None, max_pages: int = 20
    ) -> List[Dict]:
        """Collect all pages of a paginated Datatracker API response."""
        objects: List[Dict] = []
        current_path = path
        current_params = dict(params or {})
        page = 0
        while current_path and page < max_pages:
            data = await self._api_get(current_path, current_params)
            if data is None:
                break
            objects.extend(data.get("objects", []))
            next_url = data.get("meta", {}).get("next")
            if not next_url:
                break
            # next_url is relative like "/api/v1/...?offset=20&..."
            current_path = re.sub(r"^/api/v1", "", next_url.split("?")[0])
            qs = next_url.split("?")[1] if "?" in next_url else ""
            current_params = dict(pair.split("=", 1) for pair in qs.split("&") if "=" in pair)
            current_params.pop("format", None)
            page += 1
            await asyncio.sleep(0.3)
        return objects

    # ------------------------------------------------------------------
    # Config parsing
    # ------------------------------------------------------------------

    def _parse_folders(self, folders: List[str]) -> Tuple[List[str], List[str]]:
        """
        Parse the `folders` config into two lists:
          areas: list of area acronyms (from "area:{acronym}" entries)
          wgs:   list of WG acronyms   (from "wg:{acronym}" entries)
        """
        areas, wgs = [], []
        for entry in (folders or []):
            entry = entry.strip().lower()
            if entry.startswith("area:"):
                areas.append(entry[5:])
            elif entry.startswith("wg:"):
                wgs.append(entry[3:])
        return areas, wgs

    # ------------------------------------------------------------------
    # Area → WG resolution
    # ------------------------------------------------------------------

    async def _get_active_wgs_for_area(self, area_acronym: str) -> List[Dict]:
        """Return all active WG groups for a given area acronym."""
        logger.info(f"  Fetching WGs for area: {area_acronym}")
        wgs = await self._paginated_get(
            "/group/group/",
            {"type": "wg", "parent__acronym": area_acronym, "state": "active", "limit": 100},
        )
        logger.info(f"    → {len(wgs)} active WGs in {area_acronym}")
        return wgs

    async def _get_wg_info(self, wg_acronym: str) -> Optional[Dict]:
        """Fetch WG group info by acronym."""
        data = await self._api_get("/group/group/", {"acronym": wg_acronym})
        if data and data.get("objects"):
            return data["objects"][0]
        return None

    # ------------------------------------------------------------------
    # Internet-draft fetching
    # ------------------------------------------------------------------

    async def _get_recent_drafts(
        self, wg_acronym: str, lookback_days: int = 180
    ) -> List[Dict]:
        """
        Return recent internet-drafts for a WG, filtered to those
        submitted/updated within `lookback_days`.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date().isoformat()
        logger.debug(f"    Fetching drafts for {wg_acronym} since {cutoff}")
        drafts = await self._paginated_get(
            "/doc/document/",
            {
                "group__acronym": wg_acronym,
                "type": "draft",
                "time__gte": cutoff,
                "limit": 50,
            },
            max_pages=5,
        )
        return drafts

    def _draft_to_resource(
        self, draft: Dict, wg_acronym: str, area_acronym: str, datasource_id: str
    ) -> Optional[Resource]:
        """Convert a Datatracker draft dict to a Resource, or None if unusable."""
        name = draft.get("name", "")
        title = draft.get("title", name or "Untitled")
        if not title or not name:
            return None

        url = f"{DATATRACKER_BASE}/doc/{name}/"
        abstract = draft.get("abstract", "") or ""
        publish_date: Optional[str] = None
        raw_time = draft.get("time") or draft.get("rev_history", [{}])[0].get("timestamp")
        if raw_time:
            try:
                publish_date = raw_time[:10]  # ISO date
            except Exception:
                pass

        # Determine category from draft state
        state_refs: List[str] = draft.get("states", [])
        category = "internet-draft"
        # RFC check: name starts with "rfc"
        if name.startswith("rfc"):
            category = "rfc"

        return Resource(
            title=title,
            url=url,
            category=category,
            content=abstract[:1000],
            publish_date=publish_date,
            datasource_id=datasource_id,
        )

    # ------------------------------------------------------------------
    # Meeting session fetching
    # ------------------------------------------------------------------

    async def _get_recent_meetings(self) -> List[Dict]:
        """Return the last 3 IETF plenary meetings plus any recent interims."""
        meetings = await self._paginated_get(
            "/meeting/meeting/",
            {"type": "ietf", "limit": 3, "order_by": "-date"},
            max_pages=1,
        )
        return meetings

    async def _get_sessions_for_wg_at_meeting(
        self, wg_acronym: str, meeting_number: str
    ) -> List[Dict]:
        """Return sessions for a WG at a specific meeting number."""
        sessions = await self._paginated_get(
            "/meeting/session/",
            {
                "group__acronym": wg_acronym,
                "meeting__number": meeting_number,
                "limit": 10,
            },
            max_pages=1,
        )
        return sessions

    async def _session_to_event(
        self,
        session: Dict,
        wg_acronym: str,
        wg_name: str,
        meeting: Dict,
        datasource_id: str,
    ) -> Optional[Event]:
        """Convert a Datatracker session dict to an Event."""
        meeting_number = meeting.get("number", "")
        meeting_date = meeting.get("date", "")
        meeting_city = meeting.get("city", "")
        meeting_country = meeting.get("country", "")

        event_name = f"IETF {meeting_number} — {wg_name} Session"
        location = f"{meeting_city}, {meeting_country}".strip(", ") or "TBD"

        url = f"{DATATRACKER_BASE}/meeting/{meeting_number}/session/{wg_acronym}"

        # Collect material titles from the session
        material_refs: List[str] = session.get("materials", [])
        material_titles: List[str] = []
        for ref in material_refs[:8]:
            # ref is like "/api/v1/doc/document/slides-125-quic-qmux/"
            doc_name = ref.rstrip("/").rsplit("/", 1)[-1]
            material_titles.append(doc_name)

        description = f"IETF {meeting_number} {wg_name.upper()} working group session."
        if material_titles:
            description += f" Materials: {', '.join(material_titles[:6])}."

        end_date = meeting_date  # Same day — full end date unknown from API
        try:
            # Meetings last multiple days; use meeting date as start
            end_dt = datetime.strptime(meeting_date, "%Y-%m-%d") + timedelta(
                days=max(1, int(meeting.get("days", 1)) - 1)
            )
            end_date = end_dt.date().isoformat()
        except Exception:
            pass

        return Event(
            name=event_name,
            event_type="meeting",
            start_date=meeting_date or datetime.now().date().isoformat(),
            end_date=end_date,
            location=location,
            description=description,
            url=url,
            status="scheduled",
            datasource_id=datasource_id,
        )

    # ------------------------------------------------------------------
    # Per-WG scraping
    # ------------------------------------------------------------------

    async def _scrape_wg(
        self,
        wg_acronym: str,
        wg_name: str,
        area_acronym: str,
        lookback_days: int,
        scraper_delay: float,
        recent_meetings: List[Dict],
    ) -> Tuple[int, int]:
        """
        Scrape one working group: recent drafts + meeting sessions.
        Returns (resources_published, events_published).
        """
        datasource_id = f"ietf_wg_{wg_acronym}"
        res_count = 0
        evt_count = 0

        # --- Internet drafts ---
        logger.info(f"    [{wg_acronym}] Fetching recent drafts…")
        drafts = await self._get_recent_drafts(wg_acronym, lookback_days)
        for draft in drafts:
            resource = self._draft_to_resource(draft, wg_acronym, area_acronym, datasource_id)
            if resource and not self.url_exists_in_db(resource.url):
                self.publish_resource(
                    resource,
                    additional_fields={"workgroup_id": wg_acronym, "area_acronym": area_acronym},
                )
                res_count += 1
        await asyncio.sleep(scraper_delay)

        # --- Meeting sessions for recent IETF meetings ---
        for meeting in recent_meetings:
            meeting_number = meeting.get("number", "")
            if not meeting_number:
                continue
            sessions = await self._get_sessions_for_wg_at_meeting(wg_acronym, meeting_number)
            for session in sessions:
                event = await self._session_to_event(
                    session, wg_acronym, wg_name, meeting, datasource_id
                )
                if event:
                    self.publish_event(event)
                    evt_count += 1
            await asyncio.sleep(scraper_delay)

        logger.info(f"    [{wg_acronym}] Published {res_count} drafts, {evt_count} events")
        return res_count, evt_count

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_scraper(self, datasource_config: Dict[str, Any] = None):
        """
        Scrape all configured IETF areas and WGs.

        1. Parse `folders` to get enabled areas + explicit WGs.
        2. Resolve each area to its active WG list via the Datatracker API.
        3. For each unique WG: fetch recent drafts + meeting sessions.
        4. Publish Resources (datasource_id=ietf_wg_{acronym}) and Events.
        """
        if datasource_config is None:
            datasource_config = self.get_datasource_config("ietf_datatracker_api")

        datasource_id = datasource_config.get("datasource_id", "ietf_datatracker_api")
        scraper_delay = float(datasource_config.get("scraper_delay", 1.0))
        lookback_days = int(datasource_config.get("temporal_extraction_days", 180))
        folders: List[str] = datasource_config.get("folders") or []

        logger.info(f"Starting IETFDatatrackerScraper for {datasource_id}")
        logger.info(f"  Configured groups: {folders}")

        if not folders:
            logger.warning("No groups configured in folders — nothing to scrape.")
            return

        batch_id = self.start_batch(datasource_id)

        total_res = 0
        total_evt = 0

        try:
            # Resolve areas to WGs
            area_acronyms, explicit_wgs = self._parse_folders(folders)

            # Build map: wg_acronym → (wg_name, area_acronym)
            wg_map: Dict[str, Tuple[str, str]] = {}

            for area_acronym in area_acronyms:
                wg_list = await self._get_active_wgs_for_area(area_acronym)
                for wg in wg_list:
                    acr = wg.get("acronym", "")
                    name = wg.get("name", acr)
                    if acr and acr not in wg_map:
                        wg_map[acr] = (name, area_acronym)
                await asyncio.sleep(scraper_delay)

            # Add explicitly listed WGs (not already resolved via area)
            for wg_acronym in explicit_wgs:
                if wg_acronym not in wg_map:
                    info = await self._get_wg_info(wg_acronym)
                    if info:
                        wg_map[wg_acronym] = (info.get("name", wg_acronym), "")
                    else:
                        wg_map[wg_acronym] = (wg_acronym, "")
                    await asyncio.sleep(scraper_delay)

            logger.info(f"  Resolved {len(wg_map)} unique WGs to scrape")

            # Fetch recent IETF meetings once (shared across all WGs)
            recent_meetings = await self._get_recent_meetings()
            logger.info(f"  Found {len(recent_meetings)} recent IETF meetings")

            # Ensure ietf_wg_* DataSource nodes exist for all discovered WGs
            await self._ensure_wg_datasource_nodes(wg_map)

            # Scrape each WG
            for i, (wg_acr, (wg_name, area_acr)) in enumerate(wg_map.items(), 1):
                logger.info(f"  Scraping WG {i}/{len(wg_map)}: {wg_acr} ({wg_name})")
                self.update_heartbeat()
                self.update_current_processing(
                    f"ietf_wg_{wg_acr}", f"WG {i}/{len(wg_map)}"
                )
                r, e = await self._scrape_wg(
                    wg_acr, wg_name, area_acr, lookback_days, scraper_delay, recent_meetings
                )
                total_res += r
                total_evt += e
                await asyncio.sleep(scraper_delay)

            logger.info(
                f"IETFDatatrackerScraper complete — "
                f"{total_res} resources, {total_evt} events across {len(wg_map)} WGs"
            )
            self.end_batch(total_res + total_evt)

        except Exception as exc:
            logger.error(f"IETFDatatrackerScraper error: {exc}", exc_info=True)
            self.end_batch(total_res + total_evt)
            raise

    # ------------------------------------------------------------------
    # DataSource node creation for discovered WGs
    # ------------------------------------------------------------------

    async def _ensure_wg_datasource_nodes(self, wg_map: Dict[str, Tuple[str, str]]):
        """
        Create ietf_wg_* DataSource nodes in Neo4j for any WGs that don't have one yet.
        These nodes are required so users can join/ignore individual WGs and so resources
        are properly tagged.
        """
        if not self.graph_repository:
            logger.warning("No graph_repository — cannot ensure WG DataSource nodes")
            return

        # Fetch known area display names from a small lookup dict
        area_display_names = {
            "wit": "Web and Internet Transport",
            "int": "Internet Area",
            "rtg": "Routing Area",
            "sec": "Security Area",
            "art": "Applications and Real-Time Area",
            "ops": "Operations and Management Area",
            "gen": "General Area",
        }

        for wg_acr, (wg_name, area_acr) in wg_map.items():
            ds_id = f"ietf_wg_{wg_acr}"
            area_display = area_display_names.get(area_acr, area_acr.upper() if area_acr else "IETF")
            try:
                self.graph_repository.client.execute_query(
                    """
                    MERGE (d:DataSource {datasource_id: $ds_id})
                    ON CREATE SET
                        d.name          = $name,
                        d.display_name  = $display_name,
                        d.source_type   = 'ietf_wg',
                        d.area_acronym  = $area_acr,
                        d.area_name     = $area_name,
                        d.fetch_url     = $fetch_url,
                        d.has_events    = true,
                        d.created_at    = datetime()
                    ON MATCH SET
                        d.display_name  = $display_name,
                        d.area_acronym  = $area_acr,
                        d.area_name     = $area_name
                    """,
                    {
                        "ds_id": ds_id,
                        "name": f"IETF WG — {wg_name}",
                        "display_name": wg_name,
                        "area_acr": area_acr,
                        "area_name": area_display,
                        "fetch_url": f"{DATATRACKER_BASE}/wg/{wg_acr}/documents/",
                    },
                )
            except Exception as exc:
                logger.warning(f"Could not ensure DataSource node for {ds_id}: {exc}")
