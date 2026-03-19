#!/usr/bin/env bash
#
# Aurora Fast-Pipeline Test Suite
# Runs questions from cli/fast_questions.txt through the fast engine
# and shows the full Q&A with confidence scores.
#
# Usage:
#   ./test_cli_fast.sh                        # Run ALL questions
#   ./test_cli_fast.sh --random --questions=5 # Pick 5 random questions
#   ./test_cli_fast.sh --random               # Pick 5 random (default)
#   ./test_cli_fast.sh --verbose              # Include route/graph metadata
#   ./test_cli_fast.sh --datasource wfa_resource_page --questions=3 --random
#

set -e

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
CLI="./cli/aurora"
QUESTIONS_FILE="./cli/fast_questions.txt"
DATASOURCE=""
VERBOSE=false
MAX_DOCS=6
RANDOM_MODE=false
NUM_QUESTIONS=0   # 0 = run all

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case $1 in
    --random)
      RANDOM_MODE=true
      shift
      ;;
    --questions=*)
      NUM_QUESTIONS="${1#*=}"
      shift
      ;;
    --questions)
      NUM_QUESTIONS="$2"
      shift 2
      ;;
    --datasource)
      DATASOURCE="$2"
      shift 2
      ;;
    --verbose|-v)
      VERBOSE=true
      shift
      ;;
    --max-docs)
      MAX_DOCS="$2"
      shift 2
      ;;
    --questions-file)
      QUESTIONS_FILE="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --random                 Shuffle questions before selecting"
      echo "  --questions=N            Number of questions to run (default: all)"
      echo "  --datasource DS          Filter by datasource ID(s), comma-separated"
      echo "  --verbose, -v            Show route type, routing confidence, graph context"
      echo "  --max-docs N             Max documents per query (default: 6)"
      echo "  --questions-file FILE    Path to question bank (default: ./cli/fast_questions.txt)"
      echo "  --help, -h               Show this help message"
      echo ""
      echo "Examples:"
      echo "  $0 --random --questions=3           # 3 random questions, fast pipeline"
      echo "  $0 --random --questions=5 --verbose # 5 random with metadata"
      echo "  $0                                  # All questions in order"
      echo "  $0 --datasource wfa_resource_page --random --questions=4"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Load questions (skip blank lines and comments)
# ---------------------------------------------------------------------------
if [ ! -f "$QUESTIONS_FILE" ]; then
  echo "❌ Questions file not found: $QUESTIONS_FILE"
  exit 1
fi

mapfile -t ALL_QUESTIONS < <(grep -v '^\s*#' "$QUESTIONS_FILE" | grep -v '^\s*$')

TOTAL_IN_FILE=${#ALL_QUESTIONS[@]}

if [ "$TOTAL_IN_FILE" -eq 0 ]; then
  echo "❌ No questions found in $QUESTIONS_FILE"
  exit 1
fi

# ---------------------------------------------------------------------------
# Select questions
# ---------------------------------------------------------------------------
if [ "$RANDOM_MODE" = true ]; then
  # Shuffle using shuf (available on macOS via coreutils or natively on Linux)
  if command -v shuf &>/dev/null; then
    mapfile -t SHUFFLED < <(printf '%s\n' "${ALL_QUESTIONS[@]}" | shuf)
  else
    # Fallback: sort -R
    mapfile -t SHUFFLED < <(printf '%s\n' "${ALL_QUESTIONS[@]}" | sort -R)
  fi
  ALL_QUESTIONS=("${SHUFFLED[@]}")
fi

if [ "$NUM_QUESTIONS" -gt 0 ] 2>/dev/null && [ "$NUM_QUESTIONS" -lt "$TOTAL_IN_FILE" ]; then
  QUESTIONS=("${ALL_QUESTIONS[@]:0:$NUM_QUESTIONS}")
else
  QUESTIONS=("${ALL_QUESTIONS[@]}")
fi

TOTAL=${#QUESTIONS[@]}

# ---------------------------------------------------------------------------
# Build CLI flags
# ---------------------------------------------------------------------------
build_cli_flags() {
  local flags="--pipeline fast --max-documents $MAX_DOCS"

  if [ "$VERBOSE" = true ]; then
    flags="$flags -v"
  fi

  if [ -n "$DATASOURCE" ]; then
    flags="$flags --datasources $DATASOURCE"
  fi

  echo "$flags"
}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo "  Aurora Fast-Pipeline Test Suite"
echo "======================================================================"
echo "  Questions file : $QUESTIONS_FILE ($TOTAL_IN_FILE available)"
echo "  Running        : $TOTAL question(s)$([ "$RANDOM_MODE" = true ] && echo " (randomly selected)" || echo "")"
echo "  Pipeline       : fast (forced)"
echo "  Max docs       : $MAX_DOCS"
echo "  Verbose        : $VERBOSE"
[ -n "$DATASOURCE" ] && echo "  Datasource     : $DATASOURCE"
echo "======================================================================"
echo ""

if [ ! -f "$CLI" ]; then
  echo "❌ CLI not found at $CLI"
  exit 1
fi
chmod +x "$CLI"

# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------
PASS=0
FAIL=0
TOTAL_TIME=0

FLAGS=$(build_cli_flags)

for i in "${!QUESTIONS[@]}"; do
  NUM=$((i + 1))
  Q="${QUESTIONS[$i]}"

  echo "----------------------------------------------------------------------"
  echo "  Test $NUM / $TOTAL"
  echo "----------------------------------------------------------------------"

  START=$(date +%s%N 2>/dev/null || date +%s)

  # shellcheck disable=SC2086
  if $CLI $FLAGS "$Q"; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
    echo "⚠️  Query returned non-zero exit code"
  fi

  echo ""
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "  Results: $PASS passed, $FAIL failed  (of $TOTAL questions)"
echo "======================================================================"
echo ""
