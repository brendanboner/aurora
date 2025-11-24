#!/usr/bin/env python3
"""
Test script for deduplication functionality.

This script loads test fixtures and verifies that the deduplication
logic correctly identifies duplicates and keeps distinct entities separate.

Usage:
    python test_deduplication.py [--verbose] [--test-case NAME]
    
Options:
    --verbose           Show detailed output for each test
    --test-case NAME    Run only the specified test case
    --thresholds        Test with different threshold values
"""

import sys
import os
import json
import logging
from typing import List, Dict, Any
from pathlib import Path

# Add parent directory to path to import neo4j_client
sys.path.insert(0, str(Path(__file__).parent.parent))

from neo4j_client.models import Topic, Person, Organization, Resource
from neo4j_client.client import Neo4jClient
from neo4j_client.deduplicator import NodeDeduplicator
from neo4j_client.repository import GraphRepository

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_neo4j_config() -> dict:
    """Get Neo4j configuration from environment variables."""
    config = {
        'uri': os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
        'user': os.getenv('NEO4J_USER', 'neo4j'),
        'password': os.getenv('NEO4J_PASSWORD', 'password'),
        'database': os.getenv('NEO4J_DATABASE', 'neo4j')
    }
    
    # Validate required variables
    missing = [k for k, v in config.items() if not v]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing.upper())}")
    
    return config


class DeduplicationTester:
    """Test harness for deduplication functionality."""
    
    def __init__(self, client: Neo4jClient, verbose: bool = False):
        """
        Initialize tester.
        
        Args:
            client: Neo4jClient instance
            verbose: Whether to show detailed output
        """
        self.client = client
        self.repository = GraphRepository(client, logger)
        self.deduplicator = NodeDeduplicator(client, logger)
        self.verbose = verbose
        self.results = []
    
    def load_fixtures(self, fixture_file: str) -> Dict[str, Any]:
        """Load test fixtures from JSON file."""
        with open(fixture_file, 'r') as f:
            return json.load(f)
    
    def clear_test_data(self):
        """Clear all nodes from the database before running tests."""
        logger.info("Clearing database for fresh test run...")
        query = "MATCH (n) DETACH DELETE n"
        self.client.execute_write(query)
        logger.info("Database cleared")
    
    def create_topic_nodes(self, topic_data_list: List[Dict[str, Any]]) -> List[Topic]:
        """Create Topic node instances from test data."""
        topics = []
        for data in topic_data_list:
            topic = Topic(
                name=data['name'],
                classification=data['classification'],
                identifier=data.get('identifier'),
                issuer=data.get('issuer'),
                aliases=data.get('aliases', []),
                created_by='test'
            )
            topics.append(topic)
        return topics
    
    def create_person_nodes(self, person_data_list: List[Dict[str, Any]]) -> List[Person]:
        """Create Person node instances from test data."""
        people = []
        for data in person_data_list:
            person = Person(
                name=data['name'],
                email=data.get('email')
            )
            people.append(person)
        return people
    
    def create_organization_nodes(self, org_data_list: List[Dict[str, Any]]) -> List[Organization]:
        """Create Organization node instances from test data."""
        orgs = []
        for data in org_data_list:
            org = Organization(
                name=data['name'],
                org_type=data['org_type'],
                aliases=data.get('aliases', []),
                homepage_url=data.get('homepage_url')
            )
            orgs.append(org)
        return orgs
    
    def run_test_case(
        self,
        test_case: Dict[str, Any],
        similarity_threshold: float = 0.85,
        llm_review_threshold: float = 0.6
    ) -> Dict[str, Any]:
        """
        Run a single test case.
        
        Args:
            test_case: Test case data from fixtures
            similarity_threshold: Threshold for automatic deduplication
            llm_review_threshold: Threshold for LLM review
            
        Returns:
            Test result dictionary
        """
        test_name = test_case['name']
        logger.info(f"{'='*80}")
        logger.info(f"Running test: {test_name}")
        logger.info(f"Description: {test_case['description']}")
        logger.info(f"{'='*80}")
        
        # Determine node type and create nodes
        if 'topics' in test_case:
            nodes = self.create_topic_nodes(test_case['topics'])
            node_label = 'Topic'
        elif 'people' in test_case:
            nodes = self.create_person_nodes(test_case['people'])
            node_label = 'Person'
        elif 'organizations' in test_case:
            nodes = self.create_organization_nodes(test_case['organizations'])
            node_label = 'Organization'
        else:
            raise ValueError(f"Unknown node type in test case: {test_name}")
        
        # Insert the first node into the database as the baseline to match against
        if nodes:
            logger.info(f"Inserting baseline node: {nodes[0].name}")
            self.repository.create_node(nodes[0])
            logger.info(f"Baseline node inserted into database")
        
        # Run deduplication on all nodes (including the one we just inserted)
        deduplicated_nodes, duplicates_info, id_mappings = self.deduplicator._deduplicate_node_list(
            nodes,
            node_label,
            k_neighbors=5,
            similarity_threshold=similarity_threshold,
            llm_review_threshold=llm_review_threshold
        )
        
        # Clear the database after this test case
        self.clear_test_data()
        
        # Calculate results
        unique_count = len(deduplicated_nodes)
        duplicate_count = len(duplicates_info)
        expected_unique = test_case['expected_unique_count']
        expected_duplicates = test_case['expected_duplicates']
        
        # Check if test passed
        passed = (unique_count == expected_unique and duplicate_count == expected_duplicates)
        
        result = {
            'test_name': test_name,
            'passed': passed,
            'unique_count': unique_count,
            'expected_unique': expected_unique,
            'duplicate_count': duplicate_count,
            'expected_duplicates': expected_duplicates,
            'nodes': nodes,
            'deduplicated_nodes': deduplicated_nodes,
            'duplicates_info': duplicates_info,
            'id_mappings': id_mappings
        }
        
        # Log results
        status = "✓ PASSED" if passed else "✗ FAILED"
        logger.info(f"\n{status}")
        logger.info(f"Unique nodes: {unique_count} (expected: {expected_unique})")
        logger.info(f"Duplicates found: {duplicate_count} (expected: {expected_duplicates})")
        
        if self.verbose or not passed:
            logger.info(f"\nDeduplication Details:")
            logger.info(f"Original nodes: {len(nodes)}")
            
            # Show deduplication metadata for each node
            for i, node in enumerate(nodes, 1):
                logger.info(f"\n  Node {i}: {node.name}")
                if node.deduplication_score is not None:
                    logger.info(f"    Score: {node.deduplication_score:.3f}")
                if node.deduplication_best_match_name:
                    logger.info(f"    Best match: {node.deduplication_best_match_name} (ID: {node.deduplication_best_match_id})")
                else:
                    logger.info(f"    No duplicate found")
            
            if duplicates_info:
                logger.info(f"\n  Duplicate mappings:")
                for dup in duplicates_info:
                    logger.info(f"    '{dup['new_node'].name}' -> '{dup['existing_node'].get('name')}' (score: {dup['similarity_score']:.3f}, action: {dup['action']})")
        
        return result
    
    def run_threshold_tests(self, test_case: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Run a test case with different threshold values to analyze sensitivity.
        
        Args:
            test_case: Test case data
            
        Returns:
            List of results for different thresholds
        """
        threshold_configs = [
            # (0.95, 0.75, "Very High"),
            # (0.90, 0.70, "High"),
            (0.85, 0.6, "Medium (Default)"),
            # (0.80, 0.60, "Medium-Low"),
            # (0.75, 0.55, "Low")
        ]
        
        results = []
        logger.info(f"\n{'='*80}")
        logger.info(f"Threshold Sensitivity Analysis: {test_case['name']}")
        logger.info(f"{'='*80}")
        
        for sim_thresh, llm_thresh, label in threshold_configs:
            logger.info(f"\nTesting with {label} thresholds (sim={sim_thresh}, llm={llm_thresh})")
            result = self.run_test_case(test_case, sim_thresh, llm_thresh)
            result['threshold_label'] = label
            result['similarity_threshold'] = sim_thresh
            result['llm_threshold'] = llm_thresh
            results.append(result)
        
        return results
    
    def print_summary(self):
        """Print summary of all test results."""
        logger.info(f"\n{'='*80}")
        logger.info(f"TEST SUMMARY")
        logger.info(f"{'='*80}")
        
        total = len(self.results)
        passed = sum(1 for r in self.results if r['passed'])
        failed = total - passed
        
        logger.info(f"\nTotal tests: {total}")
        logger.info(f"Passed: {passed}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Success rate: {(passed/total*100):.1f}%")
        
        if failed > 0:
            logger.info(f"\nFailed tests:")
            for result in self.results:
                if not result['passed']:
                    logger.info(f"  ✗ {result['test_name']}")
                    logger.info(f"    Expected: {result['expected_unique']} unique, {result['expected_duplicates']} duplicates")
                    logger.info(f"    Got: {result['unique_count']} unique, {result['duplicate_count']} duplicates")


def main():
    """Main test runner."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Test deduplication functionality')
    parser.add_argument('--verbose', action='store_true', help='Show detailed output')
    parser.add_argument('--test-case', type=str, help='Run only specified test case')
    parser.add_argument('--thresholds', action='store_true', help='Test threshold sensitivity')
    args = parser.parse_args()
    
    # Initialize Neo4j client (requires Neo4j to be running)
    try:
        config = get_neo4j_config()
        logger.info(f"Connecting to Neo4j at {config['uri']}")
        client = Neo4jClient(
            uri=config['uri'],
            user=config['user'],
            password=config['password'],
            database=config['database']
        )
        client.connect()
        logger.info("Connected to Neo4j database")
        
        # Initialize database schema (constraints and indexes)
        logger.info("Setting up database schema...")
        client.setup_schema()
        logger.info("Database schema initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Neo4j: {e}")
        logger.error("Make sure Neo4j is running and environment variables are set")
        logger.error("Required: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE")
        sys.exit(1)
    
    # Initialize tester
    tester = DeduplicationTester(client, verbose=args.verbose)
    
    # Clear database before starting tests
    tester.clear_test_data()
    
    # Load fixtures
    fixture_file = Path(__file__).parent / 'test_deduplication_fixtures.json'
    fixtures = tester.load_fixtures(fixture_file)
    
    # Run tests
    test_cases = fixtures['test_cases']
    
    if args.test_case:
        # Run specific test case
        test_cases = [tc for tc in test_cases if tc['name'] == args.test_case]
        if not test_cases:
            logger.error(f"Test case '{args.test_case}' not found")
            client.close()
            sys.exit(1)
    
    try:
        for test_case in test_cases:
            if args.thresholds:
                # Run threshold sensitivity analysis
                threshold_results = tester.run_threshold_tests(test_case)
                tester.results.extend(threshold_results)
            else:
                # Run with default thresholds
                result = tester.run_test_case(test_case)
                tester.results.append(result)
        
        # Print summary
        tester.print_summary()
        
        # Exit with error code if any tests failed
        failed = sum(1 for r in tester.results if not r['passed'])
        exit_code = 0 if failed == 0 else 1
    finally:
        # Always close the connection
        client.close()
        logger.info("Test run complete")
    
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
