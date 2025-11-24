#!/usr/bin/env python3
"""
Test similarity functions from the deduplicator.

This script tests the similarity algorithms directly from the deduplicator
without requiring a full Neo4j setup. Test cases are loaded from JSON.
"""

import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from neo4j_client.deduplicator import NodeDeduplicator
from neo4j_client.models import Topic, Organization, Person


class MockClient:
    """Mock Neo4j client for testing."""
    def execute_query(self, query, params):
        return []
    
    def execute_write(self, query, params):
        return None


def load_test_cases():
    """Load test cases from JSON file."""
    test_file = Path(__file__).parent / "similarity_test_cases.json"
    with open(test_file, 'r') as f:
        return json.load(f)


def test_name_similarity():
    """Test name similarity using actual deduplicator method."""
    print("=" * 80)
    print("Testing Name Similarity Algorithm")
    print("=" * 80)
    
    # Initialize deduplicator with mock client
    deduplicator = NodeDeduplicator(MockClient())
    
    # Load test cases
    test_data = load_test_cases()
    test_cases = test_data.get("name_similarity_tests", [])
    
    print(f"\nRunning {len(test_cases)} test cases...")
    print("-" * 80)
    
    passed = 0
    failed = 0
    
    for test_case in test_cases:
        description = test_case["description"]
        name1 = test_case["name1"]
        name2 = test_case["name2"]
        expected_min, expected_max = test_case["expected_range"]
        should_be_duplicate = test_case["should_be_duplicate"]
        
        # Create mock nodes
        new_node = Topic(topic_id="test1", name=name1, classification="test")
        existing_node = {"name": name2}
        
        # Call the actual deduplicator method
        score = deduplicator._calculate_name_similarity(new_node, existing_node, "Topic")
        
        # Check if score is in expected range
        in_range = expected_min <= score <= expected_max
        status = "✓" if in_range else "✗"
        
        if in_range:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} {description}")
        print(f"  '{name1}' vs '{name2}'")
        print(f"  Score: {score:.3f} (expected: {expected_min:.2f}-{expected_max:.2f})")
        print(f"  Should be duplicate: {should_be_duplicate}")
        if not in_range:
            print(f"  ⚠️  FAILED - Score outside expected range")
        print()
    
    print("-" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 80)
    
    return failed == 0


def test_alias_overlap():
    """Test alias overlap using actual deduplicator method."""
    print("\n")
    print("=" * 80)
    print("Testing Alias Overlap Algorithm")
    print("=" * 80)
    
    # Initialize deduplicator with mock client
    deduplicator = NodeDeduplicator(MockClient())
    
    # Load test cases
    test_data = load_test_cases()
    test_cases = test_data.get("alias_overlap_tests", [])
    
    print(f"\nRunning {len(test_cases)} test cases...")
    print("-" * 80)
    
    passed = 0
    failed = 0
    
    for test_case in test_cases:
        description = test_case["description"]
        node1_data = test_case["node1"]
        node2_data = test_case["node2"]
        expected_min, expected_max = test_case["expected_range"]
        should_be_duplicate = test_case["should_be_duplicate"]
        
        # Create mock nodes
        new_node = Topic(
            topic_id="test1",
            name=node1_data["name"],
            classification="test",
            aliases=node1_data.get("aliases", [])
        )
        existing_node = {
            "name": node2_data["name"],
            "aliases": node2_data.get("aliases", [])
        }
        
        # Call the actual deduplicator method
        score = deduplicator._calculate_alias_overlap(new_node, existing_node)
        
        # Check if score is in expected range
        in_range = expected_min <= score <= expected_max
        status = "✓" if in_range else "✗"
        
        if in_range:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} {description}")
        print(f"  Node 1: '{node1_data['name']}' (aliases: {node1_data.get('aliases', [])})")
        print(f"  Node 2: '{node2_data['name']}' (aliases: {node2_data.get('aliases', [])})")
        print(f"  Score: {score:.3f} (expected: {expected_min:.2f}-{expected_max:.2f})")
        print(f"  Should be duplicate: {should_be_duplicate}")
        if not in_range:
            print(f"  ⚠️  FAILED - Score outside expected range")
        print()
    
    print("-" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 80)
    
    return failed == 0


def test_email_match():
    """Test email matching using actual deduplicator method."""
    print("\n")
    print("=" * 80)
    print("Testing Email Match Algorithm")
    print("=" * 80)
    
    # Initialize deduplicator with mock client
    deduplicator = NodeDeduplicator(MockClient())
    
    # Load test cases
    test_data = load_test_cases()
    test_cases = test_data.get("email_match_tests", [])
    
    print(f"\nRunning {len(test_cases)} test cases...")
    print("-" * 80)
    
    passed = 0
    failed = 0
    
    for test_case in test_cases:
        description = test_case["description"]
        node1_data = test_case["node1"]
        node2_data = test_case["node2"]
        expected_score = test_case["expected_score"]
        should_be_duplicate = test_case["should_be_duplicate"]
        
        # Create mock nodes
        new_node = Person(
            person_id="test1",
            name=node1_data["name"],
            email=node1_data.get("email")
        )
        existing_node = {
            "name": node2_data["name"],
            "email": node2_data.get("email")
        }
        
        # Call the actual deduplicator method
        score = deduplicator._calculate_email_match(new_node, existing_node)
        
        # Check if score matches expected
        matches = score == expected_score
        status = "✓" if matches else "✗"
        
        if matches:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} {description}")
        print(f"  Person 1: '{node1_data['name']}' ({node1_data.get('email', 'no email')})")
        print(f"  Person 2: '{node2_data['name']}' ({node2_data.get('email', 'no email')})")
        print(f"  Score: {score:.1f} (expected: {expected_score:.1f})")
        print(f"  Should be duplicate: {should_be_duplicate}")
        if not matches:
            print(f"  ⚠️  FAILED - Score doesn't match expected")
        print()
    
    print("-" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 80)
    
    return failed == 0


if __name__ == '__main__':
    print("\n")
    print("🧪 Similarity Function Tests")
    print("=" * 80)
    print("Testing similarity algorithms directly from NodeDeduplicator")
    print("Test cases loaded from: similarity_test_cases.json")
    print("=" * 80)
    print("\n")
    
    all_passed = True
    
    # Run all tests
    all_passed &= test_name_similarity()
    all_passed &= test_alias_overlap()
    all_passed &= test_email_match()
    
    # Summary
    print("\n")
    print("=" * 80)
    if all_passed:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed - review output above")
    print("=" * 80)
    
    sys.exit(0 if all_passed else 1)
