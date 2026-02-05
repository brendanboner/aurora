#!/usr/bin/env python3
"""
Helper script to re-ingest YouTube videos with event metadata extraction.

This script re-ingests existing YouTube videos to add event associations
and improved metadata for the video query targeting system.

Usage:
    python reingest_videos.py <video_url1> [video_url2] ...
    
Or set URLs in environment:
    export VIDEO_URLS="url1,url2,url3"
    python reingest_videos.py

Examples:
    python reingest_videos.py "https://www.youtube.com/watch?v=abc123"
    python reingest_videos.py "https://youtu.be/abc123" "https://youtu.be/def456"
"""

import argparse
import os
import requests
import sys
import time
from typing import List


def reingest_video(video_url: str, oracle_url: str, user_id: str, user_email: str) -> dict:
    """Re-ingest a YouTube video with force_redigest=true."""
    
    payload = {
        "url": video_url,
        "user_id": user_id,
        "force_redigest": True
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-User-Id": user_id,
        "X-User-Email": user_email,
        "X-User-Role": "user"
    }
    
    print(f"\n📹 Re-ingesting: {video_url}")
    print(f"   Force redigest: True")
    
    try:
        resp = requests.post(
            f"{oracle_url}/ingest/youtube",
            json=payload,
            headers=headers,
            timeout=120
        )
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ Success: {data.get('title', 'Unknown')}")
            print(f"   Video ID: {data.get('video_id')}")
            print(f"   Segments: {data.get('segments_created', 0)}")
            print(f"   Duration: {data.get('duration_seconds', 0)}s")
            return {"success": True, "data": data}
        elif resp.status_code == 409:
            # Video exists but we have force_redigest=true, so this shouldn't happen
            print(f"⚠️  Video already exists (unexpected with force_redigest=true)")
            print(f"   Response: {resp.text}")
            return {"success": False, "error": "Already exists"}
        else:
            print(f"❌ Error {resp.status_code}: {resp.text}")
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    
    except Exception as e:
        print(f"❌ Exception: {e}")
        return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Re-ingest YouTube videos with event metadata extraction"
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="YouTube video URLs to re-ingest"
    )
    parser.add_argument(
        "--oracle-url",
        default=os.getenv("AURORA_ORACLE_URL", "http://localhost:8003"),
        help="Oracle service URL (default: http://localhost:8003)"
    )
    parser.add_argument(
        "--user-id",
        default=os.getenv("TEST_USER_ID", "dev-user-123"),
        help="User ID for authentication"
    )
    parser.add_argument(
        "--user-email",
        default=os.getenv("TEST_USER_EMAIL", "dev@example.com"),
        help="User email for authentication"
    )
    parser.add_argument(
        "--from-env",
        action="store_true",
        help="Read URLs from VIDEO_URLS environment variable (comma-separated)"
    )
    
    args = parser.parse_args()
    
    # Get URLs from args or environment
    urls: List[str] = []
    
    if args.from_env or not args.urls:
        env_urls = os.getenv("VIDEO_URLS", "")
        if env_urls:
            urls = [url.strip() for url in env_urls.split(",") if url.strip()]
    
    if args.urls:
        urls.extend(args.urls)
    
    if not urls:
        print("❌ No video URLs provided")
        print("\nUsage:")
        print("  python reingest_videos.py <url1> [url2] ...")
        print("  Or set VIDEO_URLS environment variable")
        sys.exit(1)
    
    print("=" * 80)
    print("YOUTUBE VIDEO RE-INGESTION")
    print("=" * 80)
    print(f"\n📍 Oracle URL: {args.oracle_url}")
    print(f"👤 User: {args.user_email} ({args.user_id})")
    print(f"📹 Videos to re-ingest: {len(urls)}")
    print()
    
    # Check Oracle health
    try:
        health_resp = requests.get(f"{args.oracle_url}/health", timeout=5)
        if health_resp.status_code != 200:
            print(f"⚠️  Warning: Oracle health check returned {health_resp.status_code}")
    except Exception as e:
        print(f"❌ Cannot reach Oracle service at {args.oracle_url}: {e}")
        print("   Make sure the Oracle service is running:")
        print("   docker-compose up -d oracle")
        sys.exit(1)
    
    # Re-ingest each video
    results = []
    for i, url in enumerate(urls, 1):
        print(f"\n{'─' * 80}")
        print(f"Video {i}/{len(urls)}")
        
        result = reingest_video(
            video_url=url,
            oracle_url=args.oracle_url,
            user_id=args.user_id,
            user_email=args.user_email
        )
        results.append(result)
        
        # Wait between requests to avoid overwhelming the system
        if i < len(urls):
            print("\n⏳ Waiting 2s before next video...")
            time.sleep(2)
    
    # Summary
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    
    successes = sum(1 for r in results if r.get("success"))
    failures = len(results) - successes
    
    print(f"✅ Successful: {successes}/{len(results)}")
    print(f"❌ Failed: {failures}/{len(results)}")
    print()
    
    if failures == 0:
        print("🎉 All videos re-ingested successfully!")
        print()
        print("Next steps:")
        print("  1. Wait for digester to process (check logs: docker-compose logs -f digester)")
        print("  2. Run video query tests: python tests/test_video_queries.py")
    else:
        print("⚠️  Some videos failed to re-ingest. Check the errors above.")
    
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
