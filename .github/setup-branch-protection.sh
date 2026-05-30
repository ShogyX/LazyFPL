#!/usr/bin/env bash
# One-time branch protection for main, applied via the GitHub CLI.
# Run AFTER the repo exists on GitHub and you've pushed `main`:
#   gh auth login          # authenticate once
#   ./.github/setup-branch-protection.sh [owner/repo] [branch]
#
# Requires admin on the repo. Idempotent — re-running just re-applies the rules.
set -euo pipefail

REPO="${1:-ShogyX/LazyFPL}"
BRANCH="${2:-main}"

echo "Applying branch protection to $REPO@$BRANCH ..."

gh api -X PUT "repos/$REPO/branches/$BRANCH/protection" \
  --input - <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["backend", "frontend"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

# Also enable repo-level secret scanning + push protection (GitHub-hosted).
gh api -X PATCH "repos/$REPO" \
  -f security_and_analysis='{"secret_scanning":{"status":"enabled"},"secret_scanning_push_protection":{"status":"enabled"}}' \
  >/dev/null || echo "note: secret-scanning toggle may require a paid plan for private repos"

echo "Done. main now requires: passing CI (backend+frontend), 1 code-owner review, linear history, no force-push/deletion."
