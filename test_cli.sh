#!/usr/bin/env bash
#
# Aurora CLI Test Suite
# Tests the CLI against the Oracle service with various query types
#

set -e # Exit on error

# Configuration
CLI="./cli/aurora"
DATASOURCE=""    # Empty = all datasources, or set to "wfa_resource_page,wba_resource_page" etc.
PERSONALIZE=true # true = enable personalization (default), false = disable
VERBOSE=false    # true = show query metadata, false = normal output
MAX_DOCS=4       # Number of documents to retrieve per query

# Test questions array
QUESTIONS=(
  "What is Wi-Fi 7?"
  "What are the latest Wi-Fi Alliance updates?"
  "What is the latest press release?"
  "Show me press releases about 6 GHz spectrum"
  "What was discussed in the last Wi-Fi broadcast meeting"
  "What is a sticky client"
  "What documents mention 5G?"
  "What are the latest updates from WFA?"
  "What documents discuss 802.11ax?"
  "Show me documents about the upper 6 GHz band"
  "Who is talking about  RSPG?"
  "What has the Wi-Fi Alliance published about Wi-Fi 7?"
  "What happened recently regarding Wi-Fi 7?"
  "What is new in cybersecurity for wireless networking?"
  "What workgroups have people from extreme associated with them"
  "Give me any idea what was discussed in the last month"
  "Summarise recently published documents related to Wi-Fi 6E"
  "Give an update on regulatory affairs"
  "What conferences are coming up this quarter"
  "What has changed in the latest IEEE 802.11 standards?"
  "What are the key improvements in Wi-Fi 7 compared to Wi-Fi 6?"
)

# Build CLI command with options
build_cli_command() {
  local cmd="$CLI"

  if [ "$VERBOSE" = true ]; then
    cmd="$cmd -v"
  fi

  if [ -n "$DATASOURCE" ]; then
    cmd="$cmd --datasources $DATASOURCE"
  fi

  cmd="$cmd --max-documents $MAX_DOCS"

  echo "$cmd"
}

# Run a single test
run_test() {
  local num=$1
  local question=$2
  local cmd=$(build_cli_command)

  echo ""
  echo "Test $num of ${#QUESTIONS[@]}: $question"
  $cmd "$question"

  echo ""
}

# Main execution
main() {
  echo ""
  echo "======================================================================"
  echo "Aurora CLI Test Suite"
  echo "======================================================================"
  echo "CLI Command: $CLI"
  echo "Datasources: ${DATASOURCE:-all}"
  echo "Personalization: $PERSONALIZE"
  echo "Verbose: $VERBOSE"
  echo "Max Documents: $MAX_DOCS"
  echo "Total Questions: ${#QUESTIONS[@]}"
  echo "======================================================================"
  echo ""

  # Check if CLI exists
  if [ ! -f "$CLI" ]; then
    echo "Error: CLI not found at $CLI"
    exit 1
  fi

  # Make CLI executable
  chmod +x "$CLI"

  # Run all tests
  local count=1
  for question in "${QUESTIONS[@]}"; do
    run_test $count "$question"
    count=$((count + 1))
  done

  echo ""
  echo "======================================================================"
  echo "All CLI tests completed: ${#QUESTIONS[@]} questions"
  echo "======================================================================"
  echo ""
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
  --datasource)
    DATASOURCE="$2"
    shift 2
    ;;
  --verbose | -v)
    VERBOSE=true
    shift
    ;;
  --no-personalize)
    PERSONALIZE=false
    shift
    ;;
  --max-docs)
    MAX_DOCS="$2"
    shift 2
    ;;
  --help | -h)
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --datasource DS1,DS2   Filter by datasource IDs (default: all)"
    echo "  --verbose, -v          Show verbose output with metadata"
    echo "  --no-personalize       Disable personalization"
    echo "  --max-docs N           Max documents per query (default: 10)"
    echo "  --help, -h             Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                                    # Run all tests with defaults"
    echo "  $0 --verbose                          # Run with verbose output"
    echo "  $0 --datasource wfa_resource_page     # Test only WFA datasource"
    echo "  $0 --max-docs 5                       # Limit to 5 documents per query"
    exit 0
    ;;
  *)
    echo "Unknown option: $1"
    echo "Use --help for usage information"
    exit 1
    ;;
  esac
done

main
