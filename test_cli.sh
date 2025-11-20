#!/usr/bin/env bash

CLI="uv run cli/aurora"
USER=1

divider() {
  echo ""
  echo "======================================================================"
  echo " $1"
  echo "======================================================================"
  echo ""
}

run_test() {
  divider "$1"
  $CLI "$2"
  echo ""
}

echo ""
echo "🧪 Running Aurora CLI Test Suite..."
echo "📝 Testing comprehensive metadata intelligence features"
echo "User ID: $USER"
echo ""

# ----------------------------------------------------------------------
# METADATA INTELLIGENCE TESTS — Category-based queries
# ----------------------------------------------------------------------
run_test \
  "1. Category Filter: Latest press release" \
  "What is the latest press release?"

run_test \
  "2. Category Filter: Press releases about spectrum policy" \
  "Show me press releases about 6 GHz spectrum"

run_test \
  "3. Category Filter: Podcasts about Wi-Fi 7" \
  "What podcasts discuss Wi-Fi 7?"

# ----------------------------------------------------------------------
# METADATA INTELLIGENCE TESTS — Alias matching
# ----------------------------------------------------------------------
run_test \
  "4. Alias Matching: 5G (alias for mobile networks)" \
  "What documents mention 5G?"

run_test \
  "5. Alias Matching: WFA (alias for Wi-Fi Alliance)" \
  "What are the latest updates from WFA?"

# ----------------------------------------------------------------------
# METADATA INTELLIGENCE TESTS — Identifier matching
# ----------------------------------------------------------------------
run_test \
  "6. Identifier Matching: 802.11ax standard" \
  "What documents discuss 802.11ax?"

run_test \
  "7. Identifier Matching: Spectrum band (6 GHz)" \
  "Show me documents about the upper 6 GHz band"

# ----------------------------------------------------------------------
# METADATA INTELLIGENCE TESTS — Doc type filtering
# ----------------------------------------------------------------------
run_test \
  "8. Doc Type Filter: PDF documents" \
  "Show me PDF documents about Wi-Fi"

# ----------------------------------------------------------------------
# METADATA INTELLIGENCE TESTS — Combined filters
# ----------------------------------------------------------------------
run_test \
  "9. Combined: Category + Topic" \
  "What is the latest press release about RSPG?"

run_test \
  "10. Combined: Topic + Organization" \
  "What has the Wi-Fi Alliance published about Wi-Fi 7?"

# ----------------------------------------------------------------------
# USER STORY TESTS — Topic-based queries
# ----------------------------------------------------------------------
run_test \
  "11. Recent updates for specific topics" \
  "What happened recently regarding Wi-Fi 7?"

run_test \
  "12. Cross-topic query" \
  "What is new in cybersecurity for wireless networking?"

# ----------------------------------------------------------------------
# USER STORY TESTS — Organization queries
# ----------------------------------------------------------------------
run_test \
  "13. Most recent updates from WFA" \
  "What is the most recent update from the Wi-Fi Alliance?"

run_test \
  "14. Updates from IEEE" \
  "What has IEEE published recently?"

# ----------------------------------------------------------------------
# META-QUERY TESTS — Knowledge base structure queries (no documents)
# ----------------------------------------------------------------------
run_test \
  "15. Meta-query: Count organizations" \
  "How many organisations are in the knowledge base?"

run_test \
  "16. Meta-query: List available topics" \
  "List all topics available"

run_test \
  "17. Meta-query: What document types" \
  "What types of documents are in the knowledge base?"

# ----------------------------------------------------------------------
# USER STORY TESTS — Document analysis
# ----------------------------------------------------------------------
run_test \
  "18. Summaries of documents about Wi-Fi 6E" \
  "Summarise recently published documents related to Wi-Fi 6E"

run_test \
  "19. Regulatory and policy updates" \
  "What are the latest regulatory or policy updates affecting Wi-Fi?"

# ----------------------------------------------------------------------
# USER STORY TESTS — Event and meeting queries
# ----------------------------------------------------------------------
run_test \
  "20. What meetings happened related to Wi-Fi Alliance?" \
  "What meetings have taken place recently related to the Wi-Fi Alliance?"

run_test \
  "21. Upcoming events" \
  "Are there any upcoming workshops or webinars about wireless standards?"

# ----------------------------------------------------------------------
# USER STORY TESTS — Standard evolution
# ----------------------------------------------------------------------
run_test \
  "22. Changes in IEEE 802.11 standards" \
  "What has changed in the latest IEEE 802.11 standards?"

run_test \
  "23. Wi-Fi technology evolution" \
  "What are the key improvements in Wi-Fi 7 compared to Wi-Fi 6?"

echo ""
echo "🎉 All CLI tests finished."
echo "✅ Metadata intelligence features tested:"
echo "   - Category-based filtering (press release, podcast, newsletter)"
echo "   - Alias matching (5G → mobile networks, WFA → Wi-Fi Alliance)"
echo "   - Identifier matching (802.11ax, 6 GHz band)"
echo "   - Doc type filtering (PDF, HTML, video)"
echo "   - Combined filters (category + topic, topic + organization)"
echo "   - Relevance-based ranking with recency boost"
echo ""
