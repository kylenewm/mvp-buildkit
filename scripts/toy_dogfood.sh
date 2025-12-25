#!/usr/bin/env bash
set -euo pipefail

# Toy Dogfood Script - Full pack commit verification
# Usage: bash scripts/toy_dogfood.sh <approved_plan_run_id>

# 1) Safety + arg check
if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <approved_plan_run_id>"
    echo "Example: $0 66ceaedf-5273-4308-9a08-5528c3cd11f4"
    exit 2
fi

PLAN_RUN_ID="$1"
TOY_REPO="tmp/toy_repo"

echo "=== Toy Dogfood: Full Pack Commit Verification ==="
echo "Plan run: $PLAN_RUN_ID"
echo ""

# 2) Create toy repo (always fresh)
echo "[1/5] Creating fresh toy repo..."
rm -rf "$TOY_REPO"
mkdir -p "$TOY_REPO"
(
    cd "$TOY_REPO"
    git init --quiet
    echo "# Toy Repo" > README.md
    git add README.md
    git commit --quiet -m "init"
)
echo "✅ Fresh git repo created at $TOY_REPO"
echo ""

# 3) Run pack commit
echo "[2/5] Running pack commit..."
council commit-pack --project forecast_explainer --from-plan "$PLAN_RUN_ID" --repo "$TOY_REPO"
echo ""

# 4) Print outputs (sorted file list excluding .git/)
echo "[3/5] Files written to toy repo:"
echo "---"
find "$TOY_REPO" -type f | grep -v ".git/" | sort
echo "---"
echo ""

# 5) Drift check
echo "[4/5] Running drift checker..."
python scripts/check_artifacts.py
echo ""

# 6) Forbidden path assertions
echo "[5/5] Checking forbidden paths are absent..."
FAIL=0

if [[ -f "$TOY_REPO/tracker/tracker.yaml" ]]; then
    echo "❌ FAIL: tracker/tracker.yaml exists (forbidden)"
    FAIL=1
else
    echo "✅ No tracker/tracker.yaml"
fi

if [[ -f "$TOY_REPO/prompts/hotfix_sync.md" ]]; then
    echo "❌ FAIL: prompts/hotfix_sync.md exists (forbidden)"
    FAIL=1
else
    echo "✅ No prompts/hotfix_sync.md"
fi

if [[ -f "$TOY_REPO/COMMIT_MANIFEST.md" ]]; then
    echo "❌ FAIL: root COMMIT_MANIFEST.md exists (forbidden)"
    FAIL=1
else
    echo "✅ No root COMMIT_MANIFEST.md"
fi

echo ""

if [[ $FAIL -ne 0 ]]; then
    echo "❌ Toy dogfood FAILED - forbidden paths detected"
    exit 1
fi

# 7) Success message
echo "=========================================="
echo "✅ Toy dogfood complete! All checks passed."
echo "=========================================="
