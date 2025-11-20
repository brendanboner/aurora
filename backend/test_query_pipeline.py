#!/usr/bin/env python3
"""
Test script to verify the complete question-answering pipeline.

This tests:
1. User preference loading
2. LLM filter extraction
3. Filter merging
4. Neo4j query execution
5. Document summarization
"""

import sys
import os
import json

# Add backend src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from services import query_engine, postgres


def test_query_pipeline():
    """Test the complete query pipeline with different scenarios."""
    
    print("=" * 80)
    print("TESTING QUESTION-ANSWERING PIPELINE")
    print("=" * 80)
    
    # Test scenarios
    test_cases = [
        {
            "name": "Query with explicit organization mention",
            "user_id": 1,
            "question": "What are the latest updates from the Wi-Fi Alliance?"
        },
        {
            "name": "Query with technical topic",
            "user_id": 1,
            "question": "Tell me about Wi-Fi 6 and 802.11ax standards"
        },
        {
            "name": "Broad exploratory query",
            "user_id": 1,
            "question": "What's new in wireless communications?"
        },
        {
            "name": "Query with date range",
            "user_id": 1,
            "question": "What happened last week in the wireless industry?"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'=' * 80}")
        print(f"TEST CASE {i}: {test_case['name']}")
        print(f"{'=' * 80}")
        print(f"User ID: {test_case['user_id']}")
        print(f"Question: {test_case['question']}")
        print()
        
        try:
            # Check if user exists
            user = postgres.get_user_by_id(test_case['user_id'])
            if user:
                print(f"✓ User found: {user['email']}")
            else:
                print(f"✗ User {test_case['user_id']} not found - creating test user")
                user = postgres.create_user(
                    email="test@example.com",
                    display_name="Test User"
                )
                print(f"✓ Created user: {user['email']}")
            
            # Get user preferences
            prefs = postgres.get_user_preferences(test_case['user_id'])
            print(f"\nUser Preferences:")
            print(f"  Topics: {len(prefs.get('topics', []))} items")
            print(f"  Organisations: {len(prefs.get('organisations', []))} items")
            print(f"  People: {len(prefs.get('people', []))} items")
            
            # Run the query
            print(f"\n{'→' * 40}")
            print("RUNNING QUERY...")
            result = query_engine.run_query(test_case['user_id'], test_case['question'])
            
            # Display results
            print(f"\n{'✓' * 40}")
            print("QUERY RESULTS")
            print(f"{'✓' * 40}")
            
            # Filters applied
            print("\n📊 FILTERS APPLIED:")
            filters = result.get('filters', {})
            applied = filters.get('applied', {})
            from_query = filters.get('from_query', {})
            from_prefs = filters.get('from_preferences')
            
            print(f"\n  From Query (LLM extracted):")
            print(f"    Topics: {from_query.get('topics', [])}")
            print(f"    Organisations: {from_query.get('organisations', [])}")
            print(f"    People: {from_query.get('people', [])}")
            print(f"    Date range: {from_query.get('start_date')} to {from_query.get('end_date')}")
            print(f"    Limit: {from_query.get('limit')}")
            
            if from_prefs:
                print(f"\n  From User Preferences:")
                print(f"    Topics: {len(from_prefs.get('topics', []))} items")
                print(f"    Organisations: {len(from_prefs.get('organisations', []))} items")
                print(f"    People: {len(from_prefs.get('people', []))} items")
            
            print(f"\n  Final Merged Filters:")
            print(f"    Topics: {applied.get('topics', [])}")
            print(f"    Organisations: {applied.get('organisations', [])}")
            print(f"    People: {applied.get('people', [])}")
            print(f"    Limit: {applied.get('limit')}")
            
            # Documents retrieved
            doc_count = result.get('document_count', 0)
            documents = result.get('documents', [])
            
            print(f"\n📄 DOCUMENTS RETRIEVED: {doc_count}")
            if documents:
                print(f"\n  Top {min(3, len(documents))} documents:")
                for idx, doc in enumerate(documents[:3], 1):
                    print(f"\n  [{idx}] {doc.get('title', 'Untitled')}")
                    print(f"      URL: {doc.get('url', 'N/A')}")
                    print(f"      Date: {doc.get('publish_date', 'N/A')}")
                    topics = doc.get('topics', [])
                    if doc.get('topics_truncated'):
                        print(f"      Topics: {len(topics)} shown (of {doc.get('total_topics')} total)")
                    else:
                        print(f"      Topics: {len(topics)}")
                    if topics[:3]:
                        print(f"        → {', '.join(topics[:3])}")
                    orgs = doc.get('organisations', [])
                    if orgs:
                        print(f"      Organisations: {', '.join(orgs[:3])}")
            else:
                print("  ⚠ No documents found matching query")
            
            # Generated answer
            answer = result.get('answer', '')
            print(f"\n💬 GENERATED ANSWER:")
            print(f"{'─' * 80}")
            print(answer)
            print(f"{'─' * 80}")
            
            # Verify answer is not generic
            if doc_count > 0:
                generic_phrases = [
                    "I don't have information",
                    "I cannot find",
                    "No relevant documents",
                    "I don't know"
                ]
                is_generic = any(phrase.lower() in answer.lower() for phrase in generic_phrases)
                
                if is_generic:
                    print("\n⚠️  WARNING: Answer appears generic despite documents being retrieved!")
                else:
                    print("\n✅ Answer appears to be based on retrieved documents")
            
            print(f"\n{'✓' * 40}")
            print(f"TEST CASE {i} COMPLETED")
            print(f"{'✓' * 40}\n")
            
        except Exception as e:
            print(f"\n❌ ERROR in test case {i}:")
            print(f"   {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("PIPELINE TESTING COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    test_query_pipeline()
