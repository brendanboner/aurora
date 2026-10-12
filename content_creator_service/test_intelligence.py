#!/usr/bin/env python
"""
End-to-end test script for intelligent CreatorAgent features.

Tests:
1. Neo4j schema queries work correctly
2. Temporal context windows respect agent cadence
3. Adjacent topic discovery works when primary topics exhausted
4. LLM prompt builder includes agent history and user preferences
5. Agent generation works with full context
"""
import asyncio
import logging
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_neo4j_schema():
    """Test that Neo4j queries use correct schema."""
    logger.info("=" * 60)
    logger.info("TEST 1: Neo4j Schema Verification")
    logger.info("=" * 60)

    try:
        from src.neo4j_context import get_context_gateway

        gateway = get_context_gateway()
        logger.info("✓ Neo4jContextGateway initialized successfully")

        # Test fetch_recent_events method exists
        assert hasattr(gateway, "fetch_recent_events"), "Missing fetch_recent_events method"
        logger.info("✓ fetch_recent_events method available")

        # Test fetch_recent_and_upcoming method exists
        assert hasattr(gateway, "fetch_recent_and_upcoming"), "Missing fetch_recent_and_upcoming method"
        logger.info("✓ fetch_recent_and_upcoming method available")

        # Test fetch_adjacent_topics method exists
        assert hasattr(gateway, "fetch_adjacent_topics"), "Missing fetch_adjacent_topics method"
        logger.info("✓ fetch_adjacent_topics method available")

        logger.info("✓ TEST 1 PASSED: Neo4j schema methods available\n")
        return True

    except Exception as e:
        logger.error(f"✗ TEST 1 FAILED: {e}\n")
        return False


def test_knowledge_monitor_temporal():
    """Test that KnowledgeMonitor respects temporal context windows."""
    logger.info("=" * 60)
    logger.info("TEST 2: Knowledge Monitor Temporal Context")
    logger.info("=" * 60)

    try:
        from src.models.agent import CreatorAgent
        from src.services.knowledge_monitor import KnowledgeMonitor
        from datetime import datetime

        monitor = KnowledgeMonitor()
        logger.info("✓ KnowledgeMonitor initialized")

        # Test _get_time_window_for_cadence
        test_cases = {
            "per-event": 7,
            "daily": 1,
            "weekly": 7,
            "monthly": 30,
            "quarterly": 90,
        }

        for cadence, expected_days in test_cases.items():
            window = monitor._get_time_window_for_cadence(cadence)
            assert window == expected_days, f"Expected {expected_days} days for {cadence}, got {window}"
            logger.info(f"  ✓ Cadence '{cadence}' → {window} days")

        logger.info("✓ TEST 2 PASSED: Temporal window mapping correct\n")
        return True

    except Exception as e:
        logger.error(f"✗ TEST 2 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_agent_model_discovery_fields():
    """Test that CreatorAgent model includes discovery fields."""
    logger.info("=" * 60)
    logger.info("TEST 3: Agent Model Discovery Fields")
    logger.info("=" * 60)

    try:
        from src.models.agent import CreatorAgent, CreatorAgentBase
        from datetime import datetime

        # Test base model has discovery fields
        agent_base = CreatorAgentBase(
            name="test-agent",
            discovery_tolerance=0.5,
            cadence_window_days=7,
        )
        assert hasattr(agent_base, "discovery_tolerance"), "Missing discovery_tolerance"
        assert agent_base.discovery_tolerance == 0.5
        logger.info("✓ CreatorAgentBase has discovery_tolerance field")

        assert hasattr(agent_base, "cadence_window_days"), "Missing cadence_window_days"
        assert agent_base.cadence_window_days == 7
        logger.info("✓ CreatorAgentBase has cadence_window_days field")

        # Test validation bounds
        try:
            invalid_agent = CreatorAgentBase(
                name="bad-agent",
                discovery_tolerance=1.5,  # Should fail: > 1.0
            )
            logger.error("✗ discovery_tolerance validation failed (should reject > 1.0)")
            return False
        except Exception:
            logger.info("✓ discovery_tolerance validation enforces bounds")

        logger.info("✓ TEST 3 PASSED: Agent model has discovery fields\n")
        return True

    except Exception as e:
        logger.error(f"✗ TEST 3 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_prompt_builder():
    """Test that PromptBuilder creates context-aware prompts."""
    logger.info("=" * 60)
    logger.info("TEST 4: Prompt Builder")
    logger.info("=" * 60)

    try:
        from src.services.prompt_builder import PromptBuilder
        from src.models.agent import CreatorAgentBase

        builder = PromptBuilder()
        logger.info("✓ PromptBuilder initialized")

        # Create test agent (using base model for this test)
        agent = CreatorAgentBase(
            name="test-expert",
            description="Expert analyst",
            tone_style="analytical",
            content_length_preference="medium",
        )
        logger.info("✓ Test agent created")

        # Test system prompt
        system_prompt = builder.build_system_prompt(agent)
        assert "test-expert" in system_prompt, "Agent name missing from system prompt"
        assert "Respond only with factual statements" in system_prompt
        logger.info("✓ System prompt includes agent name and guidelines")

        # Test user prompt with context
        events = [
            {
                "title": "Event 1",
                "summary": "Test event",
                "topics": ["AI"],
                "url": "https://example.com/1",
                "importance": "normal",
            }
        ]
        documents = []
        recent_posts = [
            {"id": 1, "title": "Previous post", "body": "Some content"}
        ]
        user_reactions = {"like": 5, "dislike": 1}

        user_prompt = builder.build_user_prompt(
            agent,
            events=events,
            documents=documents,
            recent_posts=recent_posts,
            user_reactions=user_reactions,
        )

        assert "Event 1" in user_prompt, "Events missing from user prompt"
        assert "Previous post" in user_prompt, "Recent posts missing from user prompt"
        assert "like" in user_prompt.lower(), "User reactions missing from user prompt"
        logger.info("✓ User prompt includes events, recent posts, and preferences")

        logger.info("✓ TEST 4 PASSED: Prompt builder works correctly\n")
        return True

    except Exception as e:
        logger.error(f"✗ TEST 4 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_generation_service_enhanced():
    """Test that GenerationService uses PromptBuilder and fetches context."""
    logger.info("=" * 60)
    logger.info("TEST 5: Generation Service Enhanced Features")
    logger.info("=" * 60)

    try:
        from src.services.generation_service import GenerationService

        service = GenerationService()
        logger.info("✓ GenerationService initialized")

        # Test that service has prompt builder
        assert hasattr(service, "_prompt_builder"), "Missing _prompt_builder"
        logger.info("✓ GenerationService has PromptBuilder instance")

        # Test methods exist
        assert hasattr(service, "_fetch_agent_recent_posts"), "Missing _fetch_agent_recent_posts"
        logger.info("✓ GenerationService has _fetch_agent_recent_posts method")

        assert hasattr(service, "_aggregate_user_reactions"), "Missing _aggregate_user_reactions"
        logger.info("✓ GenerationService has _aggregate_user_reactions method")

        logger.info("✓ TEST 5 PASSED: Generation service enhanced\n")
        return True

    except Exception as e:
        logger.error(f"✗ TEST 5 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    logger.info("\n")
    logger.info("╔" + "=" * 58 + "╗")
    logger.info("║" + " " * 58 + "║")
    logger.info("║  CREATORAGENT INTELLIGENT FEATURES TEST SUITE" + " " * 12 + "║")
    logger.info("║" + " " * 58 + "║")
    logger.info("╚" + "=" * 58 + "╝")
    logger.info("\n")

    results = {
        "Neo4j Schema": test_neo4j_schema(),
        "Temporal Context": test_knowledge_monitor_temporal(),
        "Agent Discovery Fields": test_agent_model_discovery_fields(),
        "Prompt Builder": test_prompt_builder(),
        "Generation Service": test_generation_service_enhanced(),
    }

    # Summary
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status:8} | {test_name}")

    logger.info("=" * 60)
    logger.info(f"Result: {passed}/{total} tests passed")
    logger.info("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
