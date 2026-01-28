#!/usr/bin/env python3
"""Aurora Query CLI - Query the Oracle service."""

import argparse
import os
import requests
import sys
import threading
import time
import itertools
from typing import Optional, List


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
        description="CLI client for Aurora Oracle service (knowledge graph + LLM).",
    )
    parser.add_argument(
        "--oracle-url",
        default=os.getenv("AURORA_ORACLE_URL", "http://localhost:8003"),
        help="Oracle service URL (default: http://localhost:8003 or AURORA_ORACLE_URL env var)"
    )
    parser.add_argument(
        "--mode",
        choices=["retrieval", "answer", "auto"],
        default="answer",
        help="Query mode: retrieval (docs only), answer (LLM response), or auto (default: answer)"
    )
    parser.add_argument(
        "--datasources",
        help="Comma-separated datasource IDs to filter (e.g., wfa,broadcast). Default: all datasources"
    )
    parser.add_argument(
        "--max-documents",
        type=int,
        default=10,
        help="Maximum number of documents to retrieve (default: 10)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed information including query ID, confidence, and graph context"
    )
    parser.add_argument("question", nargs="+", help="Natural language question")
    args = parser.parse_args()

    # Get user context from environment variables
    user_id = os.getenv("TEST_USER_ID", "dev-user-123")
    user_email = os.getenv("TEST_USER_EMAIL", "dev@example.com")
    user_role = os.getenv("AURORA_ROLE", "user")

    question = " ".join(args.question)
    
    print(f"\n🔍 Question: {question}")
    print(f"👤 User: {user_email} ({user_id})")
    print(f"🎯 Mode: {args.mode}")
    if args.datasources:
        print(f"📊 Datasources: {args.datasources}")
    print()

    # Prepare request payload
    payload = {
        "user_id": user_id,
        "question": question,
        "mode": args.mode,
        "options": {
            "max_documents": args.max_documents,
            "personalize": "auto"  # Enable personalization by default
        }
    }
    
    # Add datasource filter if specified
    if args.datasources:
        payload["options"]["datasource_ids"] = [ds.strip() for ds in args.datasources.split(",")]
    
    # Prepare auth headers for dev/testing (bypasses Cognito)
    headers = {
        "Content-Type": "application/json",
        "X-User-Id": user_id,
        "X-User-Email": user_email,
        "X-User-Role": user_role
    }

    # Start spinner in a separate thread
    stop_spinner = threading.Event()
    spinner_message = "Querying Oracle service" if args.mode == "retrieval" else "Generating answer with Oracle"
    spinner_thread = threading.Thread(
        target=spinner, 
        args=(stop_spinner, spinner_message)
    )
    spinner_thread.start()

    try:
        resp = requests.post(
            f"{args.oracle_url}/query",
            json=payload,
            headers=headers,
            timeout=60,
        )
    except requests.RequestException as e:
        stop_spinner.set()
        spinner_thread.join()
        print(f"❌ Error contacting Oracle service: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        stop_spinner.set()
        spinner_thread.join()

    if resp.status_code != 200:
        print(f"❌ Oracle service error {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)

    data = resp.json()

    # Display verbose metadata first if requested
    if args.verbose:
        print("\n" + "=" * 80)
        print("🔍 QUERY METADATA")
        print("=" * 80)
        print(f"Query ID: {data.get('query_id', 'N/A')}")
        print(f"Pipeline: {data.get('pipeline', 'N/A')}")
        print(f"Confidence Score: {data.get('confidence_score', 'N/A')}")
        print(f"Personalization Applied: {data.get('personalization_applied', False)}")
        
        # Show graph context if available
        graph_context = data.get('graph_context')
        if graph_context:
            print(f"\nGraph Context:")
            entities = graph_context.get('entities', [])
            relationships = graph_context.get('relationships', [])
            print(f"  Entities: {len(entities)}")
            print(f"  Relationships: {len(relationships)}")
            if entities and len(entities) <= 5:
                print(f"  Top entities: {', '.join([e.get('name', '') for e in entities[:5]])}")

    # Display the answer (if in answer mode)
    if args.mode in ["answer", "auto"] and data.get('answer'):
        print("\n" + "=" * 80)
        print("💬 ANSWER")
        print("=" * 80)
        print(f"\n{data['answer']}\n")

    # Display document count and sources
    documents = data.get("documents", [])
    doc_count = len(documents)
    
    print("=" * 80)
    print(f"📄 SOURCES ({doc_count} documents retrieved)")
    print("=" * 80)
    
    if documents:
        # Show citations if available
        citations = data.get("citations", [])
        if citations and args.verbose:
            print("\nCitations used in answer:")
            for i, citation in enumerate(citations[:5], 1):
                print(f"  [{i}] {citation.get('text', '')[:100]}...")
                print(f"      Source: {citation.get('document_title', 'Unknown')}")
            print()
        
        for i, d in enumerate(documents[:10], 1):  # Show top 10
            title = d.get('title', 'Untitled')
            date = d.get('publish_date') or d.get('date', 'N/A')
            url = d.get('url', 'N/A')
            
            print(f"\n[{i}] {title}")
            print(f"    📅 {date}")
            print(f"    🔗 {url}")
            
            # Show datasource if available
            datasource = d.get('datasource_id')
            if datasource:
                print(f"    📊 Datasource: {datasource}")
            
            # Show topics if available and not too many
            topics = d.get('topics', [])
            if topics and len(topics) <= 5:
                print(f"    🏷️  {', '.join(topics)}")
            
            # Show relevance score in verbose mode
            if args.verbose and 'relevance_score' in d:
                print(f"    📈 Relevance: {d['relevance_score']:.3f}")
        
        if len(documents) > 10:
            print(f"\n... and {len(documents) - 10} more documents")
    else:
        print("\n⚠️  No documents found")
    
    # Display query suggestions if available
    suggestions = data.get("suggestions", [])
    if suggestions:
        print("\n" + "=" * 80)
        print("💡 RELATED QUERIES")
        print("=" * 80)
        for i, suggestion in enumerate(suggestions[:3], 1):
            query = suggestion.get('query') if isinstance(suggestion, dict) else suggestion
            print(f"  {i}. {query}")
    
    print("\n" + "=" * 80)
    print("✅ Query complete")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
