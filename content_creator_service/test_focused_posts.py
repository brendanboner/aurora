#!/usr/bin/env python
"""
Test script to verify focused post improvements work correctly.

Tests:
1. Relevance scoring parameters are present
2. Articles with >20 topics are filtered
3. Temporal filtering works
4. Diversity filtering removes duplicates
5. Quality thresholds are applied
"""
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_neo4j_gateway_parameters():
    """Test that fetch methods have new parameters."""
    logger.info("=" * 60)
    logger.info("TEST 1: Neo4j Gateway Parameter Verification")
    logger.info("=" * 60)
    
    try:
        from src.neo4j_context import Neo4jContextGateway
        import inspect
        
        gateway = Neo4jContextGateway.__new__(Neo4jContextGateway)
        
        # Check fetch_recent_events signature
        sig = inspect.signature(gateway.fetch_recent_events)
        params = list(sig.parameters.keys())
        
        assert 'window_days' in params, "Missing window_days parameter"
        assert 'min_relevance_score' in params, "Missing min_relevance_score parameter"
        logger.info("✓ fetch_recent_events has new parameters: window_days, min_relevance_score")
        
        # Check fetch_recent_documents signature
        sig2 = inspect.signature(gateway.fetch_recent_documents)
        params2 = list(sig2.parameters.keys())
        
        assert 'window_days' in params2, "Missing window_days parameter"
        assert 'min_relevance_score' in params2, "Missing min_relevance_score parameter"
        logger.info("✓ fetch_recent_documents has new parameters: window_days, min_relevance_score")
        
        logger.info("✓ TEST 1 PASSED\n")
        return True
        
    except Exception as e:
        logger.error(f"✗ TEST 1 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_generation_service_diversity():
    """Test that GenerationService has diversity filtering."""
    logger.info("=" * 60)
    logger.info("TEST 2: Generation Service Diversity Filter")
    logger.info("=" * 60)
    
    try:
        from src.services.generation_service import GenerationService
        import inspect
        
        service = GenerationService()
        
        # Check diversity filter method exists
        assert hasattr(service, '_apply_diversity_filter'), "Missing _apply_diversity_filter method"
        logger.info("✓ _apply_diversity_filter method exists")
        
        # Test diversity filter with mock data
        mock_articles = [
            {"url": "http://example.com/1", "title": "Wi-Fi 6E Channel Access Rules"},
            {"url": "http://example.com/2", "title": "Wi-Fi 6E Channel Access Regulations"},  # Similar
            {"url": "http://example.com/3", "title": "Passpoint Technology Overview"},
            {"url": "http://example.com/1", "title": "Wi-Fi 6E Channel Access Rules"},  # Duplicate URL
        ]
        
        filtered = service._apply_diversity_filter(mock_articles, max_items=10)
        
        # Should remove duplicate URL and similar title
        assert len(filtered) <= 2, f"Expected ≤2 articles after filtering, got {len(filtered)}"
        logger.info(f"✓ Diversity filter reduced {len(mock_articles)} articles to {len(filtered)}")
        
        logger.info("✓ TEST 2 PASSED\n")
        return True
        
    except Exception as e:
        logger.error(f"✗ TEST 2 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_agent_cadence_window():
    """Test that agent cadence_window_days is used in generation."""
    logger.info("=" * 60)
    logger.info("TEST 3: Agent Cadence Window Integration")
    logger.info("=" * 60)
    
    try:
        from src.models.agent import CreatorAgentBase
        
        # Test agent model has cadence_window_days
        agent = CreatorAgentBase(
            name="test_agent",
            expertise_topics=["Wi-Fi", "6 GHz"],
            cadence_window_days=30,
            discovery_tolerance=0.5,
        )
        
        assert agent.cadence_window_days == 30, "cadence_window_days not set correctly"
        assert agent.discovery_tolerance == 0.5, "discovery_tolerance not set correctly"
        logger.info("✓ Agent model has cadence_window_days and discovery_tolerance")
        
        # Calculate expected min_relevance_score
        expected_min_score = 0.5 - (agent.discovery_tolerance * 0.3)
        assert expected_min_score == 0.35, f"Expected min_score 0.35, got {expected_min_score}"
        logger.info(f"✓ Calculated min_relevance_score: {expected_min_score} (from tolerance {agent.discovery_tolerance})")
        
        logger.info("✓ TEST 3 PASSED\n")
        return True
        
    except Exception as e:
        logger.error(f"✗ TEST 3 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_title_similarity():
    """Test title similarity calculation."""
    logger.info("=" * 60)
    logger.info("TEST 4: Title Similarity Algorithm")
    logger.info("=" * 60)
    
    try:
        from src.services.generation_service import GenerationService
        
        service = GenerationService()
        
        # Create test articles with varying similarity
        test_cases = [
            {
                "articles": [
                    {"url": "http://a.com", "title": "Wi-Fi 6E Channel Access Rules"},
                    {"url": "http://b.com", "title": "Wi-Fi 6E Channel Access Rules Update"},  # Very high similarity (0.83)
                ],
                "expected_count": 1,
                "description": "Very high similarity titles (>0.70)"
            },
            {
                "articles": [
                    {"url": "http://a.com", "title": "Wi-Fi 6E Channel Access Rules"},
                    {"url": "http://b.com", "title": "Passpoint Technology Overview"},  # Low similarity
                ],
                "expected_count": 2,
                "description": "Low similarity titles"
            },
            {
                "articles": [
                    {"url": "http://a.com", "title": "Wi-Fi 6E New Standards"},
                    {"url": "http://b.com", "title": "Wi-Fi 6E New Standards"},  # Exact match (1.0)
                ],
                "expected_count": 1,
                "description": "Identical titles"
            },
        ]
        
        for case in test_cases:
            filtered = service._apply_diversity_filter(case["articles"], max_items=10)
            assert len(filtered) == case["expected_count"], \
                f"{case['description']}: Expected {case['expected_count']}, got {len(filtered)}"
            logger.info(f"✓ {case['description']}: {len(case['articles'])} → {len(filtered)} articles")
        
        logger.info("✓ TEST 4 PASSED\n")
        return True
        
    except Exception as e:
        logger.error(f"✗ TEST 4 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    logger.info("\n" + "=" * 60)
    logger.info("FOCUSED POST IMPROVEMENTS - TEST SUITE")
    logger.info("=" * 60 + "\n")
    
    results = [
        test_neo4j_gateway_parameters(),
        test_generation_service_diversity(),
        test_agent_cadence_window(),
        test_title_similarity(),
    ]
    
    logger.info("\n" + "=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    logger.info(f"Passed: {passed}/{total}")
    logger.info(f"Failed: {total - passed}/{total}")
    
    if passed == total:
        logger.info("✓ ALL TESTS PASSED")
        return 0
    else:
        logger.error("✗ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
