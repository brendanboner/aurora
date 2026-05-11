"""
Category Re-classification Service

One-shot Curator migration that uses the LLM to assign a proper doc_type to
Resource nodes that remain classified as 'unknown' or 'other' after the
rule-based backfill_doc_type migration.

The LLM is given the resource title and URL as context and asked to return
one of the canonical doc_type values.  This runs in small batches to avoid
rate limits and does not re-classify resources that already have a specific
doc_type.

Canonical doc_type values:
    specification, internet-draft, whitepaper, meeting-minutes,
    press-release, blog, video-transcript, case-study, infographic,
    newsletter, governing-document, agenda, presentation, unknown
"""

import json
import time
from typing import Optional

from openai import AzureOpenAI

from settings import settings
from utils.logger import setup_logger
from neo4j_client import Neo4jClient

logger = setup_logger(__name__)

VALID_DOC_TYPES = {
    "specification", "internet-draft", "whitepaper", "meeting-minutes",
    "press-release", "blog", "video-transcript", "case-study", "infographic",
    "newsletter", "governing-document", "agenda", "presentation", "unknown",
}

SYSTEM_PROMPT = """You are a document classifier for an enterprise networking knowledge base.
Given a document title and URL, return exactly ONE JSON object with a single key "doc_type".

Choose from these values ONLY:
- "specification"       — technical standards, RFCs, IEEE standards, certification specs
- "internet-draft"      — IETF drafts (draft-*), work-in-progress standards
- "whitepaper"          — research papers, industry papers, technical reports, brochures
- "meeting-minutes"     — meeting notes, attendance records, WG minutes, proceedings
- "press-release"       — press releases, announcements, news items from org newsrooms
- "blog"                — blog posts, articles, opinion pieces, editorial content
- "video-transcript"    — YouTube videos, podcasts, webinar recordings, presentations
- "case-study"          — case studies, deployment reports, success stories, use cases
- "infographic"         — infographics, visual guides, diagrams, cheat sheets
- "newsletter"          — newsletters, digest emails, highlights roundups
- "governing-document"  — bylaws, policies, membership agreements, governance docs
- "agenda"              — meeting agendas, event schedules, session outlines
- "presentation"        — slide decks, conference presentations, talks
- "unknown"             — use ONLY if none of the above fits at all

Respond with ONLY valid JSON. Example: {"doc_type": "whitepaper"}"""


class CategoryReclassifyService:
    """
    LLM-based doc_type classification for resources that rule-based mapping
    could not categorise.

    Designed to be run as a one-shot migration: call run() once; it is
    idempotent (only processes resources with doc_type = 'unknown').
    """

    BATCH_SIZE = 20      # Resources per LLM batch request
    RATE_LIMIT_DELAY = 1  # Seconds between batches

    def __init__(self, neo4j_client: Optional[Neo4jClient] = None):
        if neo4j_client is not None:
            self._client = neo4j_client
        else:
            self._client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database=settings.neo4j_database,
            )

        self._llm = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )
        self._deployment = settings.azure_openai_deployment

    def close(self):
        if self._client:
            self._client.close()

    def _classify_batch(self, resources: list[dict]) -> dict[str, str]:
        """
        Ask the LLM to classify a batch of resources.

        Returns:
            Dict mapping element_id → doc_type
        """
        lines = []
        for i, r in enumerate(resources):
            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            lines.append(f"{i+1}. Title: {title!r}  URL: {url!r}")

        user_prompt = (
            "Classify each document's doc_type. "
            "Return a JSON array where each element is {\"index\": N, \"doc_type\": \"...\"}.\n\n"
            + "\n".join(lines)
        )

        try:
            response = self._llm.chat.completions.create(
                model=self._deployment,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=512,
                temperature=0.0,
            )
            raw = response.choices[0].message.content.strip()

            # Parse JSON array
            if raw.startswith("```"):
                raw = raw.split("```")[1].strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()

            classifications = json.loads(raw)
            result = {}
            for item in classifications:
                idx = int(item.get("index", 0)) - 1
                doc_type = item.get("doc_type", "unknown").strip().lower()
                if doc_type not in VALID_DOC_TYPES:
                    doc_type = "unknown"
                if 0 <= idx < len(resources):
                    result[resources[idx]["eid"]] = doc_type
            return result

        except Exception as exc:
            logger.warning(f"CategoryReclassifyService: LLM batch classification failed: {exc}")
            return {}

    def run(self, max_resources: int = 500) -> dict:
        """
        Classify up to max_resources 'unknown' doc_type resources.

        Args:
            max_resources: Safety limit — prevents runaway LLM costs.

        Returns:
            {"classified": int, "skipped_errors": int, "remaining_unknown": int}
        """
        logger.info("CategoryReclassifyService: starting doc_type re-classification")

        fetch_query = f"""
        MATCH (r:Resource)
        WHERE toLower(r.doc_type) = 'unknown'
        RETURN elementId(r) AS eid, r.title AS title, r.url AS url
        LIMIT {max_resources}
        """
        try:
            rows = self._client.execute_query(fetch_query)
        except Exception as exc:
            logger.error(f"CategoryReclassifyService: failed to fetch resources: {exc}")
            return {"classified": 0, "skipped_errors": 1, "remaining_unknown": -1}

        if not rows:
            logger.info("CategoryReclassifyService: no 'unknown' resources to classify")
            return {"classified": 0, "skipped_errors": 0, "remaining_unknown": 0}

        logger.info(f"CategoryReclassifyService: classifying {len(rows)} resources")
        classified = 0
        errors = 0

        for batch_start in range(0, len(rows), self.BATCH_SIZE):
            batch = rows[batch_start: batch_start + self.BATCH_SIZE]
            classifications = self._classify_batch(batch)

            for eid, doc_type in classifications.items():
                if doc_type == "unknown":
                    continue  # Don't write back unknown — leave for manual review
                try:
                    self._client.execute_query(
                        "MATCH (r:Resource) WHERE elementId(r) = $eid SET r.doc_type = $doc_type",
                        {"eid": eid, "doc_type": doc_type},
                    )
                    classified += 1
                except Exception as exc:
                    logger.warning(f"CategoryReclassifyService: write failed for {eid}: {exc}")
                    errors += 1

            if batch_start + self.BATCH_SIZE < len(rows):
                time.sleep(self.RATE_LIMIT_DELAY)

        # Count how many are still unknown
        remaining_rows = self._client.execute_query(
            "MATCH (r:Resource) WHERE toLower(r.doc_type) = 'unknown' RETURN count(r) AS cnt"
        )
        remaining = remaining_rows[0].get("cnt", -1) if remaining_rows else -1

        summary = {"classified": classified, "skipped_errors": errors, "remaining_unknown": remaining}
        logger.info(f"CategoryReclassifyService: done — {summary}")
        return summary
