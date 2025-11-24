#!/usr/bin/env python3
"""Aurora Query CLI - Query the knowledge graph backend."""

import argparse
import requests
import sys
import threading
import time
import itertools


def spinner(stop_event, message="Processing"):
    """Display a spinner animation while waiting."""
    spinner_chars = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
    while not stop_event.is_set():
        sys.stdout.write(f'\r{message} {next(spinner_chars)} ')
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write('\r' + ' ' * (len(message) + 10) + '\r')  # Clear the spinner line
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        prog="aurora",
        description="CLI client for Aurora backend (knowledge graph + LLM).",
    )
    parser.add_argument(
        "--user-id", 
        type=int, 
        default=1, 
        help="User id (default: 1)"
    )
    parser.add_argument(
        "--backend",
        default="http://localhost:8000",
        help="Backend API URL (default: http://localhost:8000)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed filter information"
    )
    parser.add_argument("question", nargs="+", help="Natural language question")
    args = parser.parse_args()

    question = " ".join(args.question)
    
    print(f"\n🔍 Question: {question}")
    print(f"👤 User ID: {args.user_id}\n")

    # Start spinner in a separate thread
    stop_spinner = threading.Event()
    spinner_thread = threading.Thread(
        target=spinner, 
        args=(stop_spinner, "Querying knowledge graph and generating answer")
    )
    spinner_thread.start()

    try:
        resp = requests.post(
            f"{args.backend}/query",
            json={"user_id": args.user_id, "question": question},
            timeout=60,
        )
    except requests.RequestException as e:
        stop_spinner.set()
        spinner_thread.join()
        print(f"❌ Error contacting backend: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        stop_spinner.set()
        spinner_thread.join()

    if resp.status_code != 200:
        print(f"❌ Backend error {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)

    data = resp.json()

    # Display the answer
    print("\n" + "=" * 80)
    print("💬 ANSWER")
    print("=" * 80)
    print(f"\n{data['answer']}\n")

    # Display document count
    doc_count = data.get('document_count', len(data.get('documents', [])))
    print("=" * 80)
    print(f"📄 SOURCES ({doc_count} documents retrieved)")
    print("=" * 80)
    
    documents = data.get("documents", [])
    if documents:
        for i, d in enumerate(documents[:10], 1):  # Show top 10
            title = d.get('title', 'Untitled')
            date = d.get('publish_date', 'N/A')
            url = d.get('url', 'N/A')
            
            print(f"\n[{i}] {title}")
            print(f"    📅 {date}")
            print(f"    🔗 {url}")
            
            # Show topics if available and not too many
            topics = d.get('topics', [])
            if topics and len(topics) <= 5:
                print(f"    🏷️  {', '.join(topics)}")
        
        if len(documents) > 10:
            print(f"\n... and {len(documents) - 10} more documents")
    else:
        print("\n⚠️  No documents found")
    
    # Display filters (optional, can be hidden with a flag)
    if args.verbose:
        print("\n" + "=" * 80)
        print("🔍 FILTERS APPLIED")
        print("=" * 80)
        
        filters = data.get("filters", {})
        applied = filters.get("applied", {})
        from_query = filters.get("from_query", {})
        from_prefs = filters.get("from_preferences")
        
        print("\nFrom Query (LLM extracted):")
        print(f"  Topics: {from_query.get('topics', [])}")
        print(f"  Organisations: {from_query.get('organisations', [])}")
        print(f"  People: {from_query.get('people', [])}")
        
        if from_prefs:
            print("\nFrom User Preferences:")
            print(f"  Topics: {len(from_prefs.get('topics', []))} items")
            print(f"  Organisations: {len(from_prefs.get('organisations', []))} items")
            print(f"  People: {len(from_prefs.get('people', []))} items")
        
        print("\nFinal Merged:")
        print(f"  Topics: {applied.get('topics', [])}")
        print(f"  Organisations: {applied.get('organisations', [])}")
        print(f"  People: {applied.get('people', [])}")
    
    print("\n" + "=" * 80)
    print("✅ Query complete")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
