#!/bin/zsh
# push_backend.sh — Stage and push backend changes to the wiki-backend GitHub repo.
#
# This repo (wiki) is the source of truth for the backend code.
# The GitHub remote (origin) points to:
#   https://github.com/WeiqiangYu0528/wiki-backend.git
#
# The CI/CD pipeline (.github/workflows/deploy.yml) watches pushes to main
# for changes under backend/, Dockerfile, and docker-compose.yml, then
# SSHes into the GCP VM and runs docker-compose up -d --build automatically.
#
# IMPORTANT: Never commit .env, secrets, or API keys.
#
# Usage:
#   scripts/push_backend.sh                   # auto-commit all backend changes
#   scripts/push_backend.sh -m "your message" # use a custom commit message
#   scripts/push_backend.sh --dry-run         # show what would be committed
#
# Files tracked / always safe to push:
#   backend/          — all Python source (agent.py, main.py, etc.)
#   Dockerfile        — container build instructions
#   docker-compose.yml — service definitions
#   .github/          — CI/CD workflow
#   scripts/          — helper scripts
#
# Files that are gitignored and will NOT be included:
#   backend/.env      — local secrets (MFA secret, API keys)
#   backend/.venv/    — virtual environment
#   docs/             — wiki content (managed by sync_publish.sh instead)
#   wiki/             — third-party source repos cloned locally

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MESSAGE=""
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/push_backend.sh [options]

Stage backend source changes and push to origin (wiki-backend on GitHub).
The CI/CD pipeline will automatically redeploy to GCP on push to main.

Options:
  -m, --message TEXT   Commit message (auto-generated if omitted)
  --dry-run            Show what would be staged, but do not commit/push
  --help               Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message)
      MESSAGE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

cd "${REPO_ROOT}"

# Safety check: make sure we are on main (or let user override)
CURRENT_BRANCH="$(git branch --show-current)"
if [[ "${CURRENT_BRANCH}" != "main" ]]; then
  echo "Warning: you are on branch '${CURRENT_BRANCH}', not 'main'."
  echo "The CI/CD deploy trigger only fires on pushes to main."
  echo "Press Enter to continue, or Ctrl-C to abort."
  read -r
fi

# Show what will be staged
echo "Changes to be committed:"
git status --short backend/ Dockerfile docker-compose.yml .github/ scripts/ .gitignore 2>/dev/null || true

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo
  echo "Dry-run mode — nothing committed or pushed."
  exit 0
fi

# Stage only the backend-related files (not docs/, wiki/, etc.)
git add backend/ Dockerfile docker-compose.yml .github/ scripts/ .gitignore

if git diff --cached --quiet; then
  echo
  echo "Nothing to commit — working tree is clean for backend files."
  exit 0
fi

# Auto-generate commit message if none provided
if [[ -z "${MESSAGE}" ]]; then
  CHANGED="$(git diff --cached --name-only)"
  if echo "${CHANGED}" | grep -q "^backend/agent.py"; then
    MESSAGE="fix: update agent logic"
  elif echo "${CHANGED}" | grep -q "^backend/"; then
    MESSAGE="fix: update backend source"
  elif echo "${CHANGED}" | grep -q "docker-compose.yml\|Dockerfile"; then
    MESSAGE="fix: update docker configuration"
  else
    MESSAGE="chore: update backend files"
  fi
fi

echo
echo "Committing: ${MESSAGE}"
git commit -m "${MESSAGE}"

echo
echo "Pushing to origin/${CURRENT_BRANCH}..."
git push origin "${CURRENT_BRANCH}"

echo
echo "Done. CI/CD will redeploy to GCP automatically if pushing to main."
