#!/usr/bin/env bash
#
# Ralph Loop for Pi Coding Agent
#
# Usage:
#   ./scripts/ralph-loop-pi.sh              # Build mode, unlimited
#   ./scripts/ralph-loop-pi.sh 20           # Build mode, max 20 iterations
#   ./scripts/ralph-loop-pi.sh plan         # Planning mode, one iteration
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
CONSTITUTION="$PROJECT_DIR/.specify/memory/constitution.md"

MAX_ITERATIONS=0
MODE="build"
PI_CMD="${PI_CMD:-pi}"
PI_MODEL="${PI_MODEL:-${RALPH_PI_MODEL:-gpt-5.4-mini}}"
PI_THINKING="${PI_THINKING:-${RALPH_PI_THINKING:-high}}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

mkdir -p "$LOG_DIR"

show_help() {
  cat <<EOF
Ralph Loop for Pi Coding Agent

Usage:
  ./scripts/ralph-loop-pi.sh              # Build mode, unlimited
  ./scripts/ralph-loop-pi.sh 20           # Build mode, max 20 iterations
  ./scripts/ralph-loop-pi.sh plan         # Planning mode, one iteration

Environment:
  PI_CMD       Pi executable (default: pi)
  PI_MODEL / RALPH_PI_MODEL          Optional model pattern passed as --model
  PI_THINKING / RALPH_PI_THINKING    Thinking level passed as --thinking (default: high)

Budget examples:
  ./scripts/ralph-loop-pi.sh 1                       # default: gpt-5.4-mini, high thinking
  RALPH_PI_MODEL=gpt-5.4-mini ./scripts/ralph-loop-pi.sh 5

EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    plan)
      MODE="plan"
      if [[ "${2:-}" =~ ^[0-9]+$ ]]; then
        MAX_ITERATIONS="$2"
        shift 2
      else
        MAX_ITERATIONS=1
        shift
      fi
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    [0-9]*)
      MODE="build"
      MAX_ITERATIONS="$1"
      shift
      ;;
    *)
      echo -e "${RED}Unknown argument: $1${NC}"
      show_help
      exit 1
      ;;
  esac
done

cd "$PROJECT_DIR"

if ! command -v "$PI_CMD" >/dev/null 2>&1; then
  echo -e "${RED}Error: Pi CLI not found: $PI_CMD${NC}"
  echo "Install/authenticate Pi, then retry."
  exit 1
fi

if [[ ! -f "$CONSTITUTION" ]]; then
  echo -e "${RED}Error: missing $CONSTITUTION${NC}"
  exit 1
fi

PROMPT_FILE="PROMPT_build.md"
if [[ "$MODE" == "plan" ]]; then
  PROMPT_FILE="PROMPT_plan.md"
fi

cat > PROMPT_build.md <<'BUILDEOF'
# Ralph Loop — Build Mode for Pi

You are running inside a Ralph Wiggum autonomous loop with the Pi Coding Agent.

Read `.specify/memory/constitution.md` first. It contains project principles,
workflow instructions, autonomy settings, work sources, and completion signal
requirements.

Find the highest-priority incomplete work item, implement it completely, verify
all acceptance criteria, update history/completion logs, respect the Git
Autonomy setting, then output `<promise>DONE</promise>`.

If no incomplete specs remain, re-verify one completed spec and output
`<promise>ALL_DONE</promise>`.
BUILDEOF

cat > PROMPT_plan.md <<'PLANEOF'
# Ralph Loop — Planning Mode for Pi

You are running inside a Ralph Wiggum autonomous loop in planning mode with the
Pi Coding Agent.

Read `.specify/memory/constitution.md` for project principles. Study `specs/`
and compare against the current codebase. Create or update
`IMPLEMENTATION_PLAN.md` with a prioritized task breakdown. Do not implement
anything.

When the plan is complete, output `<promise>DONE</promise>`.
PLANEOF

SESSION_LOG="$LOG_DIR/ralph_pi_${MODE}_session_$(date '+%Y%m%d_%H%M%S').log"
exec > >(tee -a "$SESSION_LOG") 2>&1

PI_ARGS=("-p" "--thinking" "$PI_THINKING")
if [[ -n "$PI_MODEL" ]]; then
  PI_ARGS+=("--model" "$PI_MODEL")
fi

ITERATION=0
CONSECUTIVE_FAILURES=0
MAX_CONSECUTIVE_FAILURES=3

printf "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
printf "${GREEN}                 RALPH LOOP (Pi) STARTING                   ${NC}\n"
printf "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n\n"
echo -e "${BLUE}Mode:${NC}     $MODE"
echo -e "${BLUE}Prompt:${NC}   $PROMPT_FILE"
echo -e "${BLUE}Thinking:${NC} $PI_THINKING"
[[ -n "$PI_MODEL" ]] && echo -e "${BLUE}Model:${NC}    $PI_MODEL"
echo -e "${BLUE}Log:${NC}      $SESSION_LOG"
[[ $MAX_ITERATIONS -gt 0 ]] && echo -e "${BLUE}Max:${NC}      $MAX_ITERATIONS iterations"
echo ""
echo -e "${CYAN}Agent must output <promise>DONE</promise> or <promise>ALL_DONE</promise> when complete.${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop the loop.${NC}"

while true; do
  if [[ $MAX_ITERATIONS -gt 0 && $ITERATION -ge $MAX_ITERATIONS ]]; then
    echo -e "${GREEN}Reached max iterations: $MAX_ITERATIONS${NC}"
    break
  fi

  ITERATION=$((ITERATION + 1))
  LOG_FILE="$LOG_DIR/ralph_pi_${MODE}_iter_${ITERATION}_$(date '+%Y%m%d_%H%M%S').log"
  OUTPUT_FILE="$LOG_DIR/ralph_pi_output_iter_${ITERATION}_$(date '+%Y%m%d_%H%M%S').txt"

  echo ""
  echo -e "${PURPLE}════════════════════ LOOP $ITERATION ════════════════════${NC}"
  echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} Starting iteration $ITERATION"
  echo -e "${BLUE}Running:${NC} $PI_CMD ${PI_ARGS[*]} @$PROMPT_FILE"
  echo ""

  if "$PI_CMD" "${PI_ARGS[@]}" "@$PROMPT_FILE" 2>&1 | tee "$LOG_FILE" "$OUTPUT_FILE"; then
    if grep -qE '<promise>(ALL_)?DONE</promise>' "$OUTPUT_FILE" "$LOG_FILE"; then
      signal=$(grep -hoE '<promise>(ALL_)?DONE</promise>' "$OUTPUT_FILE" "$LOG_FILE" | tail -1)
      echo -e "${GREEN}✓ Completion signal detected: $signal${NC}"
      CONSECUTIVE_FAILURES=0
      if [[ "$MODE" == "plan" || "$signal" == "<promise>ALL_DONE</promise>" ]]; then
        break
      fi
    else
      echo -e "${YELLOW}⚠ No completion signal found; retrying next iteration.${NC}"
      CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
    fi
  else
    echo -e "${RED}✗ Pi execution failed. Check log: $LOG_FILE${NC}"
    CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
  fi

  if [[ $CONSECUTIVE_FAILURES -ge $MAX_CONSECUTIVE_FAILURES ]]; then
    echo -e "${RED}⚠ $MAX_CONSECUTIVE_FAILURES consecutive iterations without completion. Inspect logs before continuing.${NC}"
    CONSECUTIVE_FAILURES=0
  fi

  echo -e "${BLUE}Waiting 2s before next iteration...${NC}"
  sleep 2
done

printf "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
printf "${GREEN}        RALPH LOOP (Pi) FINISHED ($ITERATION iterations)     ${NC}\n"
printf "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
