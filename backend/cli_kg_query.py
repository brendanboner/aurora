# backend/src/cli_kg_query.py
import argparse
import textwrap

from services.llm_frontend import run_semantic_query


def main():
    parser = argparse.ArgumentParser(
        description="Semantic CLI for the knowledge graph (Neo4j + Azure OpenAI)."
    )
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        help="Natural language query (if omitted, read from stdin).",
    )
    args = parser.parse_args()

    if args.query:
        nl_query = args.query
    else:
        print("Enter your query, then Ctrl-D:")
        nl_query = "".join(iter(input, ""))  # naive stdin read

    result = run_semantic_query(nl_query)

    filters = result["filters"]
    resources = result["resources"]
    summary = result["summary"]

    print("\n=== Parsed Filters ===")
    print(filters)

    print("\n=== Matching Documents ===")
    if not resources:
        print("No matching documents found.")
    else:
        for row in resources:
            r = row["resource"]
            print(f"- {r.get('publish_date') or r.get('scraped_at')} | {r.get('title')}")
            print(f"  URL: {r.get('url')}")
            topics = [t.get("name") for t in row.get("topics", []) if t.get("name")]
            orgs = [o.get("name") for o in row.get("organisations", []) if o.get("name")]
            if topics:
                print(f"  Topics: {', '.join(topics)}")
            if orgs:
                print(f"  Organisations: {', '.join(orgs)}")
            print()

    print("\n=== LLM Summary ===")
    print(textwrap.fill(summary, width=100))


if __name__ == "__main__":
    main()
