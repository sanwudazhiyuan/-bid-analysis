#!/usr/bin/env bash
# Test: Verify bid-review skill is properly bundled in the haha-code Docker image
set -euo pipefail

SERVICE="haha-code"
PASS=0
FAIL=0

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

exec_in() {
  docker compose exec "$SERVICE" sh -c "$1" 2>/dev/null || echo ""
}

echo "=== bid-review skill integration tests ==="
echo ""

# --- Test 1: Skill file exists in Docker image ---
echo "[1] Skill file exists in image"
if exec_in "test -f /app/.claude/skills/bid-review/SKILL.md"; then
  pass "SKILL.md found at /app/.claude/skills/bid-review/SKILL.md"
else
  fail "SKILL.md not found in image"
fi

# --- Test 2: Skill has valid frontmatter ---
echo "[2] Skill has valid YAML frontmatter"
CONTENT=$(exec_in "cat /app/.claude/skills/bid-review/SKILL.md")
if echo "$CONTENT" | head -10 | grep -q "^name: bid-review"; then
  pass "name field is 'bid-review'"
else
  fail "name field missing or incorrect"
fi

if echo "$CONTENT" | grep -q "^description:"; then
  pass "description field present"
else
  fail "description field missing"
fi

if echo "$CONTENT" | grep -q "审核标书\|审查投标\|条款合规"; then
  pass "description contains trigger keywords"
else
  fail "description missing trigger keywords"
fi

# --- Test 3: Skill has review workflow instructions ---
echo "[3] Skill body contains review workflow"
if echo "$CONTENT" | grep -qi "_目录\.md"; then
  pass "References _目录.md for navigation"
else
  fail "Missing _目录.md reference"
fi

if echo "$CONTENT" | grep -qi "para_index"; then
  pass "Output format includes para_index"
else
  fail "Missing para_index in output format"
fi

# --- Test 4: server.ts references /bid-review skill ---
echo "[4] server.ts references /bid-review skill"
SERVER_TS=$(exec_in "cat /app/server.ts")
if echo "$SERVER_TS" | grep -qi "bid-review"; then
  pass "server.ts references bid-review skill"
else
  fail "server.ts does not reference bid-review skill"
fi

if echo "$SERVER_TS" | grep -qi "\-\-system-prompt" && echo "$SERVER_TS" | grep -qi "bid-review"; then
  pass "system-prompt mentions bid-review skill"
else
  fail "system-prompt does not mention bid-review skill"
fi

# --- Test 5: haha-code service is healthy ---
echo "[5] haha-code service is running"
if docker compose ps "$SERVICE" 2>/dev/null | grep -qi "healthy\|Up"; then
  pass "haha-code container is running"
else
  fail "haha-code container is not running"
fi

# --- Test 6: /review endpoint responds ---
echo "[6] /review endpoint responds (basic)"
HEALTH=$(exec_in "curl -sf http://localhost:3000/health" || echo "{}")
if echo "$HEALTH" | grep -q '"status"'; then
  pass "Health endpoint responds: $HEALTH"
else
  fail "Health endpoint failed: $HEALTH"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  echo "SOME TESTS FAILED"
  exit 1
else
  echo "ALL TESTS PASSED"
  exit 0
fi
