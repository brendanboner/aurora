#!/usr/bin/env bash
# =============================================================================
# Aurora Demo Runner — self-paced teleprompter + auto-runner
#
# Usage:
#   ./doc/demo/demo_runner.sh           # full 30-min demo
#   ./doc/demo/demo_runner.sh --setup   # pre-demo health checks only
#   ./doc/demo/demo_runner.sh --act 2   # jump to a specific act
#   ./doc/demo/demo_runner.sh --warmup  # cache warm-up queries only
#
# The script:
#   - Displays speech text in large readable blocks (teleprompter style)
#   - Auto-runs CLI queries and shows the answer
#   - Pauses at browser-UI steps with on-screen instructions
#   - Shows a running clock and per-segment timer
#   - Saves a timestamped transcript to /tmp/aurora-demo-<date>.log
# =============================================================================

set -euo pipefail

# ── Terminal colours ──────────────────────────────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[0;33m'
BLU='\033[0;34m'
MAG='\033[0;35m'
CYN='\033[0;36m'
WHT='\033[1;37m'
RST='\033[0m'

# ── Config ────────────────────────────────────────────────────────────────────
DEMO_START_TIME=""
LOG_FILE="/tmp/aurora-demo-$(date +%Y%m%d-%H%M%S).log"
START_ACT="${2:-1}"
FULL_WIDTH=$(tput cols 2>/dev/null || echo 80)
AURORA_CLI="./cli/aurora"

# ── Helpers ───────────────────────────────────────────────────────────────────

hr() { printf "${DIM}%${FULL_WIDTH}s${RST}\n" | tr ' ' '─'; }

header() {
  local title="$1" timing="$2"
  echo
  hr
  printf "${BOLD}${BLU}  %-*s${YLW}  %s${RST}\n" "$((FULL_WIDTH-20))" "$title" "$timing"
  hr
  echo
}

elapsed() {
  if [[ -z "$DEMO_START_TIME" ]]; then echo "  --:--"; return; fi
  local now elapsed mins secs
  now=$(date +%s)
  elapsed=$((now - DEMO_START_TIME))
  mins=$((elapsed / 60))
  secs=$((elapsed % 60))
  printf "  %02d:%02d" "$mins" "$secs"
}

speech() {
  echo
  printf "${YLW}${BOLD}  ┌─ SPEAK ─────────────────────────────────────────────────────────${RST}\n"
  while IFS= read -r line; do
    printf "${WHT}  │  %s${RST}\n" "$line"
  done <<< "$1"
  printf "${YLW}${BOLD}  └─────────────────────────────────────────────────────────────────${RST}\n"
  echo
}

action() {
  echo
  printf "${GRN}${BOLD}  ▶ ACTION: %s${RST}\n" "$1"
  echo
}

browser() {
  echo
  printf "${MAG}${BOLD}  🌐 BROWSER — type into Aurora chat:${RST}\n"
  printf "${WHT}${BOLD}  ┌────────────────────────────────────────────────────────────────${RST}\n"
  printf "${WHT}${BOLD}  │  %s${RST}\n" "$1"
  printf "${WHT}${BOLD}  └────────────────────────────────────────────────────────────────${RST}\n"
  # Copy to clipboard silently
  printf '%s' "$1" | pbcopy 2>/dev/null || true
  printf "${DIM}  (copied to clipboard)${RST}\n"
  echo
}

pause() {
  local msg="${1:-Press ENTER to continue}"
  printf "${CYN}  ⏸  %s ${RST}" "$msg"
  read -r _
  echo
}

run_query() {
  local q="$1" label="${2:-}"
  echo
  printf "${BLU}${BOLD}  ▶ Running query%s${RST}\n" "${label:+: $label}"
  printf "${DIM}  %s${RST}\n" "$q"
  echo
  # Tee to log, strip ANSI from log
  "$AURORA_CLI" --pipeline fast "$q" 2>/dev/null | tee >(sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE")
  echo
}

status_check() {
  local label="$1" ok=true
  printf "  Checking %-40s" "$label..."
  shift
  if "$@" &>/dev/null; then
    printf "${GRN}✓${RST}\n"
  else
    printf "${RED}✗ FAILED${RST}\n"
    ok=false
  fi
  $ok
}

segment_timer() {
  local target_min="$1"
  local now elapsed target_sec remain_sec remain_min remain_s colour
  now=$(date +%s)
  elapsed=$((now - DEMO_START_TIME))
  target_sec=$((target_min * 60))
  remain_sec=$((target_sec - elapsed))
  if (( remain_sec < 0 )); then
    remain_sec=$(( -remain_sec ))
    remain_min=$((remain_sec / 60))
    remain_s=$((remain_sec % 60))
    printf "${RED}  ⏱  +%02d:%02d over target  Elapsed: %s${RST}\n" "$remain_min" "$remain_s" "$(elapsed)"
  else
    remain_min=$((remain_sec / 60))
    remain_s=$((remain_sec % 60))
    colour="${GRN}"
    (( remain_sec < 60 )) && colour="${YLW}"
    printf "${colour}  ⏱  %02d:%02d remaining   Elapsed: %s${RST}\n" "$remain_min" "$remain_s" "$(elapsed)"
  fi
}

# ── Setup / health checks ─────────────────────────────────────────────────────
run_setup() {
  clear
  header "🔧  Aurora Demo — Pre-flight Checks" "$(date '+%H:%M')"

  echo "  Running health checks before the demo..."
  echo

  local all_ok=true

  # Oracle health
  status_check "Oracle service" curl -sf http://localhost:8002/health || all_ok=false

  # Auth health
  status_check "Auth service" curl -sf http://localhost:8001/health || all_ok=false

  # Backend health
  status_check "Backend service" curl -sf http://localhost:8000/health || all_ok=false

  # Redis reachable
  status_check "Redis" docker compose exec -T redis redis-cli ping || all_ok=false

  # Neo4j node count
  status_check "Neo4j has data" bash -c 'docker compose exec -T neo4j cypher-shell -u neo4j -p "$(grep NEO4J_PASSWORD .env | cut -d= -f2)" "MATCH (n) RETURN count(n) as c" 2>/dev/null | grep -v "^c$" | grep -qE "^[1-9]"' || all_ok=false

  # CLI smoke query
  echo
  printf "  Running smoke query (first call — may take 10–15 s cold)...\n"
  if "$AURORA_CLI" --pipeline fast "What is the difference between Wi-Fi 7 and Wi-Fi 8?" 2>/dev/null | grep -q "Wi-Fi"; then
    printf "  %-45s${GRN}✓${RST}\n" "Smoke query returns content"
  else
    printf "  %-45s${RED}✗ Thin or empty response — check oracle logs${RST}\n" "Smoke query"
    all_ok=false
  fi

  echo
  hr

  if $all_ok; then
    printf "${GRN}${BOLD}  ✅  All checks passed. Ready to demo.${RST}\n"
  else
    printf "${RED}${BOLD}  ❌  One or more checks failed. Fix before presenting.${RST}\n"
    printf "${DIM}  Run: docker compose logs -f oracle   to diagnose.${RST}\n"
  fi
  echo
}

# ── Cache warm-up ─────────────────────────────────────────────────────────────
run_warmup() {
  clear
  header "🔥  Cache Warm-up" "$(date '+%H:%M')"

  echo "  Flushing stale fast cache..."
  docker compose exec -T redis redis-cli EVAL \
    "local k=redis.call('keys',ARGV[1]) for i=1,#k,5000 do redis.call('del',unpack(k,i,math.min(i+4999,#k))) end return #k" \
    0 "fast:*" 2>/dev/null && echo "  Cache flushed." || echo "  (Redis not reachable locally — flush on EC2 if needed)"

  echo
  local queries=(
    "@wba what's new in NextGen Wi-Fi this month"
    "What are the priorities of the IoT programme this quarter?"
    "What is the difference between Wi-Fi 7 and Wi-Fi 8?"
    "@wifi8mtg what has been discussed recently in the Wi-Fi 8 task group?"
    "What has Qualcomm contributed to Wi-Fi 8 discussions?"
  )

  for q in "${queries[@]}"; do
    printf "${DIM}  Warming: %s${RST}\n" "$q"
    "$AURORA_CLI" --pipeline fast "$q" 2>/dev/null | grep -E "completed in|Pipeline" || true
    echo
  done

  printf "${GRN}  ✅  Warm-up complete. All queries should now return in <5 s.${RST}\n"
  echo
}

# ── Individual acts ───────────────────────────────────────────────────────────

act_intro() {
  clear
  DEMO_START_TIME=$(date +%s)
  echo "$DEMO_START_TIME" > /tmp/aurora-demo-start.txt

  header "🎬  COLD OPEN — The Problem" "0:00 → 2:30"

  speech "How many of you have read every WBA NextGen Wi-Fi meeting note from the last month?
Right. How many have read every IETF draft and IEEE 802.11 agenda since February?

Every product team at Extreme is trying to track standards bodies that move faster than
any one person can read. We pay membership fees. We send people to meetings. But the
knowledge stays locked in PDFs and minutes that almost nobody opens.

Aurora reads them for you. It pulls the public standards record from IETF and IEEE,
the member-only working-group activity from the WBA Extranet, and folds them into one
place you can ask questions of — in plain English, in your browser."

  action "Switch to the Aurora web tab now."
  pause "Ready for Act 1? (ENTER)"
  segment_timer 2
}

act1() {
  clear
  header "ACT 1 — Login & Personalisation" "2:30 → 7:00"

  speech "Sixty seconds. That's all there is to it. Aurora now knows what to dig into and
what to leave aside. And it respects access control — you only see what you've joined."

  action "1. Click Log in → SSO → land on Aurora home"
  pause "Done? (ENTER)"

  action "2. Click your avatar / Profile in the top-right → profile page opens"
  action "   'Groups & Sources' tab is selected by default (new in this build)"
  action "   Scroll to 'WBA Extranet' → find 'Wi-Fi 8 - Ultra High Reliability'"
  action "   Click JOIN (note the gold member-only badge — this is gated content)"
  action "   Also join 'AI/ML for Wi-Fi' and 'E2E Wi-Fi QoS, L4S & EDCA'"
  printf "${DIM}  Real WBA workgroup names: Wi-Fi 7, Wi-Fi 8 - Ultra High Reliability,${RST}\n"
  printf "${DIM}  AI/ML for Wi-Fi, 5G & Wi-Fi Convergence, Security & Post-Quantum Computing${RST}\n\n"
  pause "Done? (ENTER)"

  action "3. Switch to 'Sources' tab → join 'WFA Resource Page' and 'IEEE 802.11'"
  action "4. Switch to 'Technology' tab → search Wi-Fi 8 → click star | search PQC → click star"
  pause "Done? Groups joined, topics starred (ENTER)"

  speech "Sixty seconds. Aurora now knows what to dig into and what to leave aside.
It respects access control — you only see what you've joined."

  segment_timer 7
  pause "Ready for Act 2? (ENTER)"
}

act2() {
  clear
  header "ACT 2 — Member-Only Standards Access" "7:00 → 14:00"

  speech "The @wba mention scopes this to Wireless Broadband Alliance sources. Aurora expands
it to every WBA workgroup I have access to — filtering against member-only meeting
digests that require a login to reach."

  browser "@wba what's new in NextGen Wi-Fi this month"
  action "Type that into Aurora chat now. While it loads, speak the line above."
  pause "Query sent? (ENTER to show fallback tip)"
  printf "${DIM}  Fallback if thin: @wba what has the Wi-Fi 8 Ultra High Reliability workgroup done?${RST}\n\n"
  pause "Answer landed? Point out a named person and workgroup. (ENTER)"

  browser "What are the priorities of the IoT programme this quarter?"
  action "Type the second query. Click a source card while it renders."
  pause "Done? (ENTER)"

  speech "Cross-workgroup synthesis. The IoT programme has six sub-groups. Aurora rolls them up."
  action "Optional: briefly show Admin Monitoring tab — active scrape list, recent activity."
  pause "Ready for Act 3? (ENTER)"
  segment_timer 14
}

act3() {
  clear
  header "ACT 3 — Cross-Source Synthesis" "14:00 → 19:00"

  speech "This answer lives in seven places: IEEE 802.11bn drafts, Wi-Fi Alliance certification
proposals, WBA Extranet working-group discussions, and the public press. No single
document has it. Aurora composes one."

  browser "What is the difference between Wi-Fi 7 and Wi-Fi 8?"
  action "Type into Aurora chat. While it loads, speak the line above."
  pause "Answer landed? Point at the source list — call out IEEE, WFA, WBA, IETF. (ENTER)"

  browser "Which of those benefits matters most for enterprise deployments?"
  action "Type the follow-up. No extra context needed — Aurora keeps the turn."
  pause "Done? (ENTER)"

  speech "Aurora is keeping context across turns. We're not restating the comparison —
we're asking it to pivot."

  printf "${DIM}  Fallback: What has Qualcomm contributed to Wi-Fi 8 discussions?${RST}\n\n"
  pause "Ready for Act 4? (ENTER)"
  segment_timer 19
}

act4() {
  clear
  header "ACT 4 — Create Your Own Agent" "19:00 → 24:00"

  speech "This isn't just chat — users can deploy passive, scheduled assistants.
Daily digests in your voice, on your topics, against the same knowledge base.
One per project. Architects build agents for customer briefings.
PMs build agents that watch a single workgroup."

  action "1. Navigate to My Agents → Create agent"
  action "2. Fill in:"
  printf "     ${WHT}Name:       Wi-Fi 8 Daily Brief${RST}\n"
  printf "     ${WHT}Persona:    Senior wireless architect. Dry, technical tone.${RST}\n"
  printf "               ${WHT}Focus on chip-side implications.${RST}\n"
  printf "     ${WHT}Topics:     802.11be, 802.11bn, latency optimization${RST}\n"
  printf "     ${WHT}Orgs:       IEEE, WBA, WFA${RST}\n"
  printf "     ${WHT}Cadence:    daily-digest${RST}\n"
  echo
  pause "Ready to click Create? (ENTER)"

  action "3. Click Create → then click Run now on the new agent."
  action "4. Wait ~30 s, then refresh the Feed pane."
  pause "Post appeared in the feed? Read the title aloud. (ENTER)"

  speech "Daily digests in your voice, on your topics. One per project.
Architects can build agents for customer briefings.
Product managers can build agents that watch a single workgroup."

  printf "${DIM}  Fallback: Show an existing agent post from the feed and walk the same flow.${RST}\n\n"
  pause "Ready for Act 5? (ENTER)"
  segment_timer 24
}

act5() {
  clear
  header "ACT 5 — Teams: Group Intelligence + Broadcasts" "24:00 → 27:30"

  speech "Aurora isn't just a personal chat tool. It works in team channels too —
and it's smart about when to speak up.

Two scenarios: the bot listening in a group conversation and proactively
adding context; and the system broadcasting a critical standards update
to every relevant channel automatically."

  action "Open the Agents Playground. Make sure it's connected to the bot."
  echo
  action "SCENARIO A — Group context awareness:"
  printf "     ${WHT}Type this in the Playground (simulating a colleague's message):${RST}\n"
  browser "do we know how Wi-Fi 8 will affect handover between APs?"
  action "The bot detects a standards question and adds relevant context."
  action "Point out: it didn't wait to be asked directly — it recognised the topic."
  pause "Response appeared? (ENTER)"

  echo
  action "SCENARIO B — System announcement (new terminal):"
  printf "     ${DIM}  make teams-test-announce${RST}\n"
  printf "     ${DIM}  (pushes an IEEE 802.11bn D2.0 ballot update to all channels)${RST}\n\n"
  printf "     ${WHT}Run this in a separate terminal, then watch the Playground.${RST}\n"
  action "The announcement appears as a broadcast — no user triggered it."
  pause "Announcement delivered? (ENTER)"

  speech "Two patterns: reactive (bot responds when the conversation needs it)
and proactive (system pushes breaking updates automatically).
Both work across personal chat AND team channels. No new tool to learn."

  pause "Ready to close? (ENTER)"
  segment_timer 27
}

act_close() {
  clear
  header "CLOSE & ASK" "27:30 → 30:00"

  speech "Aurora is a prototype from the Office of the CTO Rapid AI Innovation team.
The architecture is built. The data is flowing.

What needs finishing: corporate Teams deployment with IT this week, a guided
first-run setup, and the proactive push from agents that's plumbed but not wired.

We are inviting 25 people across Extreme to a one-week pilot starting Wednesday.

Three things I'm asking from this room:
  1. Nominate people for the pilot.
  2. Point us at the working groups your teams care about most.
  3. Tell us where this lands on your roadmap."

  pause "Ready for Q&A? (ENTER)"
  segment_timer 30

  echo
  printf "${GRN}${BOLD}  ✅  Demo complete. Log saved to: %s${RST}\n" "$LOG_FILE"
  echo
}

# ── Quick-fire fallback queries (run live from terminal) ──────────────────────
run_live_query() {
  local q="$1"
  clear
  header "🔍  Live Query" "$(elapsed)"
  run_query "$q" "live"
  pause "Done? (ENTER to return)"
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  # Parse flags
  local mode="demo"
  local jump_act=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --setup)   mode="setup"; shift ;;
      --warmup)  mode="warmup"; shift ;;
      --act)     mode="demo"; jump_act="${2:-1}"; shift 2 ;;
      --query)   shift; run_live_query "$*"; exit 0 ;;
      *) shift ;;
    esac
  done

  case "$mode" in
    setup)  run_setup; exit 0 ;;
    warmup) run_warmup; exit 0 ;;
  esac

  # Full demo
  mkdir -p "$(dirname "$LOG_FILE")"
  printf "Aurora Demo Log — %s\n%s\n\n" "$(date)" "$(hr | sed 's/\x1b\[[0-9;]*m//g')" > "$LOG_FILE"

  # Jump to act
  if [[ "$jump_act" -le 0 ]] || [[ "$jump_act" -eq 1 ]]; then act_intro; fi
  if [[ "$jump_act" -le 1 ]] || [[ "$jump_act" -eq 1 ]]; then act1; fi
  if [[ "$jump_act" -le 2 ]] || [[ "$jump_act" -eq 2 ]]; then act2; fi
  if [[ "$jump_act" -le 3 ]] || [[ "$jump_act" -eq 3 ]]; then act3; fi
  if [[ "$jump_act" -le 4 ]] || [[ "$jump_act" -eq 4 ]]; then act4; fi
  if [[ "$jump_act" -le 5 ]] || [[ "$jump_act" -eq 5 ]]; then act5; fi
  act_close
}

main "$@"
