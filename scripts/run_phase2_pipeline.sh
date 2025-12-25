#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Phase 2 Pipeline Runner
# Runs: spec → tracker → prompts → cursor-rules → invariants
# Each artifact is approved and committed to tmp/toy_repo
# =============================================================================

usage() {
    echo "Usage: $0 <approved_plan_run_id> <models_csv> <chair_model>"
    echo ""
    echo "Example:"
    echo "  $0 cf3b8be9-... 'google/gemini-3-flash-preview,google/gemini-3-flash-preview' google/gemini-3-flash-preview"
    exit 2
}

# Check args
if [[ $# -ne 3 ]]; then
    usage
fi

PLAN_RUN_ID="$1"
MODELS="$2"
CHAIR="$3"
PROJECT="cli_changes"
TOY_REPO="tmp/toy_repo"

echo "=============================================="
echo "Phase 2 Pipeline Runner"
echo "=============================================="
echo "Plan run: $PLAN_RUN_ID"
echo "Models: $MODELS"
echo "Chair: $CHAIR"
echo "Project: $PROJECT"
echo "Target: $TOY_REPO"
echo ""

# Helper: extract run_id from council output
extract_run_id() {
    local output="$1"
    local plan_id="$2"
    # Look for "Run ID: <uuid>" or "run_id: <uuid>" pattern
    # Then filter out the plan_id to get the NEW run
    local run_id
    run_id=$(echo "$output" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | grep -v "$plan_id" | head -1)
    echo "$run_id"
}

# Helper: fail with debug info
fail_step() {
    local step="$1"
    local run_id="${2:-unknown}"
    echo ""
    echo "❌ FAILED at step: $step"
    echo ""
    echo "Debug commands:"
    if [[ "$run_id" != "unknown" ]]; then
        echo "  council show $run_id --section errors"
        echo "  council show $run_id --section synthesis"
        echo "  council show $run_id --section all"
    fi
    echo ""
    exit 1
}

# =============================================================================
# Step 1: Reset toy repo
# =============================================================================
echo "[1/6] Resetting toy repo..."
rm -rf "$TOY_REPO"
mkdir -p "$TOY_REPO"
(
    cd "$TOY_REPO"
    git init --quiet
    echo "# Toy Repo - Phase 2 Pipeline Test" > README.md
    git add README.md
    git commit --quiet -m "init"
)
echo "✅ Toy repo initialized"
echo ""

# =============================================================================
# Step 2: Run each Phase 2 council
# =============================================================================

run_council() {
    local artifact="$1"
    local step_num="$2"
    
    echo "[${step_num}/6] Running $artifact council..."
    
    local output
    if ! output=$(council run "$artifact" \
        --from-plan "$PLAN_RUN_ID" \
        --project "$PROJECT" \
        --models "$MODELS" \
        --chair "$CHAIR" 2>&1); then
        echo "$output"
        fail_step "$artifact council run" "unknown"
    fi
    
    echo "$output"
    
    # Extract run_id (filter out the plan_id)
    local run_id
    run_id=$(extract_run_id "$output" "$PLAN_RUN_ID")
    
    if [[ -z "$run_id" ]]; then
        echo ""
        echo "⚠️  Could not extract run_id from output."
        echo "PASTE THE RUN_ID HERE and run these commands manually:"
        echo "  council approve <run_id> --approve"
        echo "  council commit <run_id> --repo $TOY_REPO"
        echo "  git -C $TOY_REPO add -A && git -C $TOY_REPO commit -m '$artifact'"
        exit 2
    fi
    
    echo ""
    echo "Run ID: $run_id"
    
    # Approve
    echo "Approving..."
    if ! council approve "$run_id" --approve 2>&1; then
        fail_step "$artifact approve" "$run_id"
    fi
    echo "✅ Approved"
    
    # Ensure toy repo is clean before commit
    local dirty
    dirty=$(git -C "$TOY_REPO" status --porcelain)
    if [[ -n "$dirty" ]]; then
        echo "⚠️  Toy repo dirty before commit, committing..."
        git -C "$TOY_REPO" add -A
        git -C "$TOY_REPO" commit --quiet -m "pre-$artifact cleanup" || true
    fi
    
    # Commit to toy repo
    echo "Committing to toy repo..."
    if ! council commit "$run_id" --repo "$TOY_REPO" 2>&1; then
        fail_step "$artifact commit" "$run_id"
    fi
    echo "✅ Committed"
    
    # Commit toy repo to keep it clean for next artifact
    git -C "$TOY_REPO" add -A
    git -C "$TOY_REPO" commit --quiet -m "$artifact: $run_id" || true
    echo "✅ Toy repo committed"
    echo ""
}

# Run all councils in order
run_council "spec" "2"
run_council "tracker" "3"
run_council "prompts" "4"
run_council "cursor-rules" "5"
run_council "invariants" "6"

# =============================================================================
# Step 3: Final checks
# =============================================================================
echo "[7/7] Running final checks..."
echo ""

# Drift check
echo "Running drift checker..."
if ! python scripts/check_artifacts.py; then
    echo "❌ Drift checker failed"
    exit 1
fi
echo ""

# Forbidden paths check
echo "Checking forbidden paths in toy repo..."
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

if [[ -f "$TOY_REPO/docs/build_guide.md" ]]; then
    echo "❌ FAIL: docs/build_guide.md exists (forbidden)"
    FAIL=1
else
    echo "✅ No docs/build_guide.md"
fi

if [[ -f "$TOY_REPO/COMMIT_MANIFEST.md" ]]; then
    echo "❌ FAIL: root COMMIT_MANIFEST.md exists (forbidden)"
    FAIL=1
else
    echo "✅ No root COMMIT_MANIFEST.md"
fi

echo ""

if [[ $FAIL -ne 0 ]]; then
    echo "❌ Forbidden paths check FAILED"
    exit 1
fi

# =============================================================================
# Final output
# =============================================================================
echo "=============================================="
echo "✅ Phase 2 Pipeline Complete!"
echo "=============================================="
echo ""
echo "Files in toy repo:"
find "$TOY_REPO" -type f | grep -v ".git/" | sort
echo ""
echo "Git log:"
git -C "$TOY_REPO" log --oneline

