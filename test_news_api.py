#!/usr/bin/env python3
"""
Test script for the News API endpoint.
Tests different time ranges and verifies the response structure.
"""

import requests
import json
import sys
from datetime import datetime

BACKEND_URL = "http://localhost:8000"

def test_news_endpoint(user_id: int = 1, time_range: str = "1month", force_refresh: bool = False):
    """Test the news endpoint with given parameters."""
    print(f"\n{'='*60}")
    print(f"Testing News Endpoint")
    print(f"User ID: {user_id}")
    print(f"Time Range: {time_range}")
    print(f"Force Refresh: {force_refresh}")
    print(f"{'='*60}\n")
    
    try:
        # Make request to news endpoint
        response = requests.post(
            f"{BACKEND_URL}/news",
            json={
                "user_id": user_id,
                "time_range": time_range,
                "force_refresh": force_refresh
            },
            timeout=120  # Allow up to 2 minutes for LLM generation
        )
        
        if response.status_code != 200:
            print(f"❌ Error: HTTP {response.status_code}")
            print(f"Response: {response.text}")
            return False
        
        # Parse response
        data = response.json()
        
        # Verify response structure
        print("✓ Response received successfully")
        print(f"\nHeadline: {data.get('headline', 'N/A')}")
        print(f"\nTime Range: {data.get('time_range', 'N/A')}")
        print(f"Documents Analyzed: {data.get('document_count', 0)}")
        print(f"Generated At: {data.get('generated_at', 'N/A')}")
        
        # Display summary
        summary = data.get('summary', '')
        if summary:
            print(f"\nSummary Preview:")
            print(f"{summary[:200]}..." if len(summary) > 200 else summary)
        
        # Display sections
        sections = data.get('sections', [])
        print(f"\nSections: {len(sections)}")
        for i, section in enumerate(sections, 1):
            print(f"  {i}. {section.get('title', 'Untitled')}")
            doc_count = len(section.get('documents', []))
            if doc_count > 0:
                print(f"     ({doc_count} related documents)")
        
        # Display highlights
        highlights = data.get('highlights', [])
        if highlights:
            print(f"\nKey Highlights ({len(highlights)}):")
            for i, highlight in enumerate(highlights, 1):
                print(f"  {i}. {highlight}")
        
        print(f"\n{'='*60}")
        print("✅ Test passed successfully!")
        print(f"{'='*60}\n")
        
        return True
        
    except requests.exceptions.Timeout:
        print("❌ Error: Request timed out (LLM generation took too long)")
        return False
    except requests.exceptions.ConnectionError:
        print("❌ Error: Could not connect to backend. Is it running?")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run multiple tests with different time ranges."""
    print("\n" + "="*60)
    print("News API Test Suite")
    print("="*60)
    
    # Check backend health
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=5)
        if response.status_code != 200:
            print("❌ Backend health check failed")
            sys.exit(1)
        print("✓ Backend is healthy")
    except Exception as e:
        print(f"❌ Cannot connect to backend: {e}")
        sys.exit(1)
    
    # Test different time ranges
    time_ranges = ["1week", "1month", "6months", "1year"]
    results = []
    
    for time_range in time_ranges:
        # First request (may generate fresh content)
        success = test_news_endpoint(user_id=1, time_range=time_range, force_refresh=False)
        results.append((time_range, "fresh", success))
        
        if not success:
            print(f"⚠️  Skipping cached test for {time_range} due to failure")
            continue
        
        # Second request (should use cache)
        print(f"\nTesting cached response for {time_range}...")
        success = test_news_endpoint(user_id=1, time_range=time_range, force_refresh=False)
        results.append((time_range, "cached", success))
    
    # Print summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    
    for time_range, test_type, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {time_range} ({test_type})")
    
    # Overall result
    total_tests = len(results)
    passed_tests = sum(1 for _, _, success in results if success)
    
    print(f"\nTotal: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total_tests - passed_tests} test(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
