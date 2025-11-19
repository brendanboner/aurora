#!/usr/bin/env bash

CLI="./cli/aurora"
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
  $CLI --user-id=$USER "$2"
  echo ""
}

echo ""
echo "🧪 Running Aurora CLI Test Suite..."
echo "User ID: $USER"
echo ""

# ----------------------------------------------------------------------
# USER STORY 1 — “What happened last week in topics x, y, z?”
# ----------------------------------------------------------------------
run_test \
  "1. Recent updates for specific topics (Wi-Fi 7, WPA3, Passpoint)" \
  "What happened last week regarding Wi-Fi 7, WPA3, or Passpoint?"

# ----------------------------------------------------------------------
# USER STORY 2 — “Give me updates from specific organisations”
# ----------------------------------------------------------------------
run_test \
  "2. Most recent updates from WFA" \
  "What is the most recent update from WFA?"

run_test \
  "3. Updates from IEEE 802.11 Task Group" \
  "What has IEEE 802.11 published recently?"

# ----------------------------------------------------------------------
# USER STORY 3 — “Meeting summaries”
# ----------------------------------------------------------------------
run_test \
  "4. What meetings happened this month related to Wi-Fi Alliance?" \
  "What meetings have taken place this month related to the Wi-Fi Alliance?"

run_test \
  "5. Summaries of all recent standards meetings" \
  "Summarise all standards meetings that happened in the last two weeks."

# ----------------------------------------------------------------------
# USER STORY 4 — “Upcoming events”
# ----------------------------------------------------------------------
run_test \
  "6. Upcoming Wi-Fi or security events next 90 days" \
  "What upcoming Wi-Fi or network security events are happening in the next 90 days?"

run_test \
  "7. Are there any relevant webinars or workshops soon?" \
  "Are there any upcoming workshops or webinars about wireless standards?"

# ----------------------------------------------------------------------
# USER STORY 5 — “Cross-cutting topics”
# ----------------------------------------------------------------------
run_test \
  "8. What is new in cybersecurity for wireless networking?" \
  "What is new in cybersecurity for wireless networking this month?"

run_test \
  "9. What are the latest regulatory updates affecting Wi-Fi?" \
  "What are the latest regulatory or policy updates affecting Wi-Fi?"

# ----------------------------------------------------------------------
# USER STORY 6 — “Recommendations”
# ----------------------------------------------------------------------
run_test \
  "10. Recommend relevant meetings or events for my interests" \
  "Based on my interests in Wi-Fi, WPA3, and enterprise security, what meetings or events should I attend in the next few months?"

run_test \
  "11. Which colleagues are attending events I may care about?" \
  "Which colleagues are attending upcoming events or meetings related to my areas of interest?"

# ----------------------------------------------------------------------
# USER STORY 7 — “Document Analysis”
# ----------------------------------------------------------------------
run_test \
  "12. Summaries of documents about Wi-Fi 6E or AFC" \
  "Summarise recently published documents related to Wi-Fi 6E or AFC systems."

# ----------------------------------------------------------------------
# USER STORY 8 — “Standard evolution”
# ----------------------------------------------------------------------
run_test \
  "13. What changed in recent IEEE 802.11 drafts?" \
  "What has changed in the latest draft versions of IEEE 802.11 standards?"

# ----------------------------------------------------------------------
# USER STORY 9 — “Source-based filtering”
# ----------------------------------------------------------------------
run_test \
  "14. Show recent updates from public sources only" \
  "Show me the recent updates from public sources only."

run_test \
  "15. What did members-only sites publish last week?" \
  "What member-only content was published last week by WFA or IEEE?"

# ----------------------------------------------------------------------
# USER STORY 10 — “Cross-reference people, orgs and topics”
# ----------------------------------------------------------------------
run_test \
  "16. Show all updates involving person X or organisation Y" \
  "Show updates involving John Doe or the Wi-Fi Alliance from the last month."

echo ""
echo "🎉 All CLI tests finished."
echo ""
