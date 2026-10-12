"""CLI helper to trigger a CreatorAgent run on demand."""
from __future__ import annotations

import argparse
import logging
from typing import Optional

from .. import db
from ..services.agent_service import AgentService
from ..services.scheduler import AgentScheduler

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Force a CreatorAgent to generate content for testing purposes.",
    )
    parser.add_argument("--agent-id", type=int, help="Numeric ID of the CreatorAgent to run")
    parser.add_argument(
        "--agent-name",
        type=str,
        help="Case-insensitive name of the CreatorAgent to run (alternative to --agent-id)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip cadence/importance gating and allow reusing the last processed event",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of recent events to sample when evaluating the run (default: 5)",
    )
    return parser


def resolve_agent(agent_service: AgentService, *, agent_id: Optional[int], agent_name: Optional[str]):
    if not agent_id and not agent_name:
        raise SystemExit("Provide --agent-id or --agent-name")
    try:
        if agent_id is not None:
            return agent_service.get_agent(agent_id)
        assert agent_name is not None
        return agent_service.get_agent_by_name(agent_name)
    except Exception as exc:  # pragma: no cover - surface API errors nicely
        detail = getattr(exc, "detail", str(exc))
        raise SystemExit(f"Agent lookup failed: {detail}") from exc


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()

    if args.limit <= 0:
        parser.error("--limit must be greater than zero")

    db.init_pool()
    agent_service = AgentService()
    scheduler = AgentScheduler()

    try:
        agent = resolve_agent(
            agent_service,
            agent_id=args.agent_id,
            agent_name=args.agent_name,
        )
        post_id, event = scheduler.run_agent_once(
            agent.id,
            force=args.force,
            limit=args.limit,
        )
    finally:
        db.close_pool()

    event_label = event.title if event and event.title else (event.fingerprint() if event else "n/a")
    if post_id:
        print(
            f"✅ Agent '{agent.name}' generated post {post_id} using event '{event_label}'."
        )
    else:
        if event is None:
            print(
                f"⚠️ Agent '{agent.name}' had no eligible events. Try widening its focus or increasing --limit."
            )
        else:
            print(
                f"ℹ️ Agent '{agent.name}' processed event '{event_label}' but no content was created. "
                "Check the content creator logs for details."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
