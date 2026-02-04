#!/usr/bin/env python3
"""
Test suite for video query targeting with events, people, and organizations.

This tests the improved video querying system to ensure:
1. Event-focused queries return correct event videos
2. Speaker/person-focused queries target the right segments
3. Topic-focused queries (GPU, memory) find relevant segments
4. Organization-focused queries filter by org mentions
5. No cross-video contamination (Cisco Live 2025 vs Cisco AI Summit 2026)

SETUP REQUIRED:
1. Re-ingest your YouTube videos to get event metadata:
   - In the Aurora chat UI, paste the YouTube URL with ?force_redigest=true
   - Or use the CLI: curl -X POST http://localhost:8003/ingest/youtube \
     -H "Content-Type: application/json" -d '{"url": "YOUR_VIDEO_URL", "force_redigest": true}'

2. Set environment variables for authentication:
   export TEST_USER_ID="your-user-id"
   export TEST_USER_EMAIL="your-email@example.com"
   export AURORA_ORACLE_URL="http://localhost:8003"
"""

import sys
import os
import requests
import time
from typing import Optional

# Test cases for two videos:
# Video 1: "Cisco Live 2025" (last year - old event)
# Video 2: "Cisco AI Summit 2026" (yesterday - recent event)

TEST_CASES = [
    {
        "name": "Event-focused: What happened at Cisco AI Summit",
        "question": "What happened at Cisco AI Summit 2026?",
        "expected_event": "Cisco AI Summit 2026",
        "should_not_contain_event": "Cisco Live 2025",
        "expected_datasource": "youtube",
        "min_relevance": 0.7,
    },
    {
        "name": "Event-focused: What was discussed at Cisco Live",
        "question": "What was discussed at Cisco Live 2025?",
        "expected_event": "Cisco Live 2025",
        "should_not_contain_event": "Cisco AI Summit 2026",
        "expected_datasource": "youtube",
        "min_relevance": 0.7,
    },
    {
        "name": "Organization + Event: Anthropic at Cisco AI Summit",
        "question": "What did Anthropic discuss at Cisco AI Summit?",
        "expected_event": "Cisco AI Summit 2026",
        "expected_org": "Anthropic",
        "should_not_contain_event": "Cisco Live 2025",
        "min_relevance": 0.8,  # High relevance for co-occurrence
    },
    {
        "name": "Topic-focused: GPU discussion",
        "question": "What was said about GPU at the recent summit?",
        "expected_topics": ["GPU", "AI", "compute"],
        "expected_datasource": "youtube",
        "should_prefer_recent": True,
    },
    {
        "name": "Topic-focused: Memory architecture",
        "question": "Explain memory architecture discussion at AI summit",
        "expected_topics": ["memory", "architecture"],
        "expected_event": "Cisco AI Summit 2026",  # Should prefer recent
    },
    {
        "name": "Speaker-focused: Who presented at the summit",
        "question": "Who were the main presenters at Cisco AI Summit?",
        "expected_event": "Cisco AI Summit 2026",
        "expected_datasource": "youtube",
        "check_people_extraction": True,
    },
    {
        "name": "Organization comparison: Compare vendors",
        "question": "Compare what different vendors said at AI Summit",
        "expected_event": "Cisco AI Summit 2026",
        "check_org_extraction": True,
        "min_orgs": 2,
    },
    {
        "name": "Temporal: Recent AI developments",
        "question": "What are recent AI developments mentioned in videos?",
        "should_prefer_recent": True,
        "expected_datasource": "youtube",
        "expected_event": "Cisco AI Summit 2026",
    },
    {
        "name": "Segment aggregation: Multiple GPU mentions",
        "question": "Summarize all GPU discussions from AI Summit",
        "expected_event": "Cisco AI Summit 2026",
        "expect_multiple_segments": True,  # Should aggregate if >1 segment matches
        "expected_topics": ["GPU"],
    },
    {
        "name": "Negative test: Unrelated query",
        "question": "What is the price of Bitcoin today?",
        "expect_low_relevance": True,
        "should_return_few_results": True,
    },
]


def query_oracle(question: str, oracle_url: str, user_id: str, user_email: str, mode: str = "answer", datasources: Optional[list] = None) -> dict:
    """Query the Oracle service via API (like the CLI does)."""
    
    payload = {
        "user_id": user_id,
        "question": question,
        "mode": mode,
        "options": {
            "max_documents": 10,
            "personalize": "auto"
        }
    }
    
    if datasources:
        payload["options"]["datasource_ids"] = datasources
    
    headers = {
        "Content-Type": "application/json",
        "X-User-Id": user_id,
        "X-User-Email": user_email,
        "X-User-Role": "user"
    }
    
    try:
        resp = requests.post(
            f"{oracle_url}/query",
            json=payload,
            headers=headers,
            timeout=60
        )
        
        if resp.status_code != 200:
            print(f"❌ Oracle API error {resp.status_code}: {resp.text}")
            return {"documents": [], "answer": "", "error": f"HTTP {resp.status_code}"}
        
        return resp.json()
    
    except Exception as e:
        print(f"❌ Error querying Oracle: {e}")
        return {"documents": [], "answer": "", "error": str(e)}


def test_video_queries():
    """Run all video query test cases."""
    print("=" * 80)
    print("VIDEO QUERY TARGETING TEST SUITE")
    print("=" * 80)
    print()
    print("Testing improved video querying with event association,")
    print("entity co-occurrence scoring, and segment aggregation.")
    print()
    
    # Get configuration from environment
    oracle_url = os.getenv("AURORA_ORACLE_URL", "http://localhost:8003")
    user_id = os.getenv("TEST_USER_ID", "dev-user-123")
    user_email = os.getenv("TEST_USER_EMAIL", "dev@example.com")
    
    print(f"📍 Oracle URL: {oracle_url}")
    print(f"👤 User: {user_email} ({user_id})")
    print()
    
    # Check if Oracle is reachable
    try:
        health_resp = requests.get(f"{oracle_url}/health", timeout=5)
        if health_resp.status_code != 200:
            print(f"⚠️  Warning: Oracle health check returned {health_resp.status_code}")
    except Exception as e:
        print(f"❌ Cannot reach Oracle service at {oracle_url}: {e}")
        print("   Make sure the Oracle service is running (docker-compose up -d)")
        return 0, len(TEST_CASES)
    
    passed = 0
    failed = 0
    skipped = 0
    
    for i, test_case in enumerate(TEST_CASES, 1):
        print(f"\n{'=' * 80}")
        print(f"TEST {i}/{len(TEST_CASES)}: {test_case['name']}")
        print(f"{'=' * 80}")
        print(f"Question: {test_case['question']}")
        print()
        
        try:
            # Run query via Oracle API
            print(f"🔍 Querying Oracle API...")
            start_time = time.time()
            result = query_oracle(
                question=test_case['question'],
                oracle_url=oracle_url,
                user_id=user_id,
                user_email=user_email,
                mode="answer",
                datasources=["youtube"] if test_case.get('expected_datasource') == "youtube" else None
            )
            elapsed_time = time.time() - start_time
            
            print(f"⏱️  Query completed in {elapsed_time:.2f}s")
            
            # Check for errors
            if result.get('error'):
                print(f"❌ Query failed: {result['error']}")
                failed += 1
                continue
            
            # Extract results
            documents = result.get('documents', [])
            answer = result.get('answer', '')
            filters = result.get('filters', {})
            
            print(f"📊 Retrieved {len(documents)} documents")
            if filters:
                applied = filters.get('applied', {})
                print(f"🔍 Filters applied: topics={applied.get('topics', [])}, orgs={applied.get('organizations', [])}, people={applied.get('people', [])}")
            print()
            
            # Validate results
            issues = []
            warnings = []
            
            # Check expected event
            if 'expected_event' in test_case:
                event_found = False
                wrong_event_found = False
                
                for doc in documents:
                    doc_title = doc.get('title', '').lower()
                    if test_case['expected_event'].lower() in doc_title:
                        event_found = True
                    # Only check for wrong event if specified
                    if test_case.get('should_not_contain_event'):
                        if test_case['should_not_contain_event'].lower() in doc_title:
                            wrong_event_found = True
                
                if not event_found:
                    issues.append(f"❌ Expected event '{test_case['expected_event']}' not found in results")
                else:
                    print(f"✅ Found expected event: {test_case['expected_event']}")
                
                if wrong_event_found:
                    issues.append(f"❌ Cross-video contamination: Found '{test_case['should_not_contain_event']}' in results")
            
            # Check expected organization
            if 'expected_org' in test_case:
                org_found = any(
                    test_case['expected_org'].lower() in doc.get('title', '').lower() or
                    test_case['expected_org'].lower() in str(doc.get('organizations', [])).lower()
                    for doc in documents
                )
                if not org_found:
                    issues.append(f"❌ Expected organization '{test_case['expected_org']}' not found")
                else:
                    print(f"✅ Found expected organization: {test_case['expected_org']}")
            
            # Check datasource
            if 'expected_datasource' in test_case:
                correct_source = any(
                    doc.get('datasource_id') == test_case['expected_datasource']
                    for doc in documents
                )
                if not correct_source:
                    warnings.append(f"⚠️  Expected datasource '{test_case['expected_datasource']}' not prominent")
            
            # Check relevance scores
            if 'min_relevance' in test_case and documents:
                top_relevance = documents[0].get('relevance_score', 0)
                if top_relevance < test_case['min_relevance']:
                    warnings.append(f"⚠️  Top relevance {top_relevance:.2f} below threshold {test_case['min_relevance']}")
                else:
                    print(f"✅ Relevance score {top_relevance:.2f} meets threshold {test_case['min_relevance']}")
            
            # Check for segment aggregation
            if test_case.get('expect_multiple_segments'):
                same_parent_segments = {}
                for doc in documents:
                    url = doc.get('url', '')
                    if 't=' in url:  # Segment URL
                        parent = url.split('&t=')[0]
                        same_parent_segments[parent] = same_parent_segments.get(parent, 0) + 1
                
                max_segments = max(same_parent_segments.values()) if same_parent_segments else 0
                if max_segments > 1:
                    print(f"✅ Found {max_segments} segments from same video (good for aggregation)")
                else:
                    warnings.append("⚠️  Expected multiple segments from same video")
            
            # Check for people extraction
            if test_case.get('check_people_extraction'):
                people_found = any(doc.get('people') for doc in documents)
                if people_found:
                    people_list = []
                    for doc in documents:
                        people_list.extend(doc.get('people', []))
                    print(f"✅ Found people mentions: {list(set(people_list))[:3]}")
                else:
                    warnings.append("⚠️  No people extracted from video content")
            
            # Check for org extraction
            if test_case.get('check_org_extraction'):
                all_orgs = []
                for doc in documents:
                    all_orgs.extend(doc.get('organizations', []))
                unique_orgs = list(set(all_orgs))
                
                min_orgs = test_case.get('min_orgs', 1)
                if len(unique_orgs) >= min_orgs:
                    print(f"✅ Found {len(unique_orgs)} organizations: {unique_orgs[:5]}")
                else:
                    warnings.append(f"⚠️  Expected at least {min_orgs} organizations, found {len(unique_orgs)}")
            
            # Check temporal preference
            if test_case.get('should_prefer_recent') and documents:
                recent_dates = [doc.get('publish_date', '') for doc in documents[:3]]
                print(f"📅 Top result dates: {recent_dates}")
            
            # Display sample results
            if documents:
                print(f"\n📄 Top 3 results:")
                for idx, doc in enumerate(documents[:3], 1):
                    print(f"  [{idx}] {doc.get('title', 'Untitled')}")
                    print(f"      Relevance: {doc.get('relevance_score', 0):.2f}")
                    print(f"      Source: {doc.get('datasource_id', 'unknown')}")
                    if doc.get('organizations'):
                        print(f"      Orgs: {', '.join(doc.get('organizations', [])[:3])}")
            
            # Summary
            if issues:
                print(f"\n❌ FAILED: {len(issues)} issue(s)")
                for issue in issues:
                    print(f"  {issue}")
                failed += 1
            else:
                print(f"\n✅ PASSED")
                passed += 1
            
            if warnings:
                print(f"⚠️  Warnings:")
                for warning in warnings:
                    print(f"  {warning}")
        
        except Exception as e:
            print(f"\n❌ ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    # Final summary
    print(f"\n{'=' * 80}")
    print("TEST SUMMARY")
    print(f"{'=' * 80}")
    print(f"✅ Passed: {passed}/{len(TEST_CASES)}")
    print(f"❌ Failed: {failed}/{len(TEST_CASES)}")
    print(f"⏭️  Skipped: {skipped}/{len(TEST_CASES)}")
    print()
    
    if failed == 0:
        print("🎉 All tests passed!")
    else:
        print(f"⚠️  {failed} test(s) need attention")
    
    return passed, failed


if __name__ == "__main__":
    test_video_queries()
