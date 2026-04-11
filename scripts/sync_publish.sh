#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PUBLISH_DIR="${PUBLISH_DIR:-$HOME/Projects/LLM_Knowledge_Base}"
SITE_URL="${SITE_URL:-https://weiqiangyu0528.github.io/LLM_Knowledge_Base/}"
REPO_URL="${REPO_URL:-https://github.com/WeiqiangYu0528/LLM_Knowledge_Base}"
MESSAGE=""
DRY_RUN=0
NO_PUSH=0
NO_COMMIT=0

usage() {
  cat <<'EOF'
Usage: scripts/sync_publish.sh [options]

Sync publishable wiki content from the local working tree into the GitHub Pages
publish repo, prepare a deployment-safe mkdocs.yml, then optionally commit/push.

Options:
  --publish-dir PATH   Override the publish repo directory
  --message TEXT       Use an explicit commit message
  --dry-run            Sync files and show the resulting diff, but do not commit/push
  --no-commit          Sync files but do not create a commit
  --no-push            Commit locally but do not push
  --help               Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --publish-dir)
      PUBLISH_DIR="$2"
      shift 2
      ;;
    --message)
      MESSAGE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --no-commit)
      NO_COMMIT=1
      shift
      ;;
    --no-push)
      NO_PUSH=1
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

if [[ ! -d "${SOURCE_ROOT}/docs" ]]; then
  echo "Source docs directory not found: ${SOURCE_ROOT}/docs" >&2
  exit 1
fi

if [[ ! -f "${SOURCE_ROOT}/mkdocs.yml" ]]; then
  echo "Source mkdocs.yml not found: ${SOURCE_ROOT}/mkdocs.yml" >&2
  exit 1
fi

if [[ ! -d "${PUBLISH_DIR}" ]]; then
  echo "Publish directory not found: ${PUBLISH_DIR}" >&2
  exit 1
fi

if ! git -C "${PUBLISH_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Publish directory is not a git repository: ${PUBLISH_DIR}" >&2
  exit 1
fi

echo "Syncing docs/ -> ${PUBLISH_DIR}/docs"
rsync -a --delete \
  --exclude '.DS_Store' \
  "${SOURCE_ROOT}/docs/" "${PUBLISH_DIR}/docs/"

find "${PUBLISH_DIR}/docs" -name '.DS_Store' -delete

python3 "${SCRIPT_DIR}/prepare_publish_mkdocs.py" \
  "${SOURCE_ROOT}/mkdocs.yml" \
  "${PUBLISH_DIR}/mkdocs.yml" \
  --site-url "${SITE_URL}" \
  --repo-url "${REPO_URL}"

echo
echo "Working tree status:"
git -C "${PUBLISH_DIR}" status --short

if [[ -z "$(git -C "${PUBLISH_DIR}" status --short)" ]]; then
  echo
  echo "No publishable changes detected."
  exit 0
fi

echo
echo "Diff summary:"
git -C "${PUBLISH_DIR}" diff --stat

generate_message() {
  local changed_files wiki_count wiki_label
  local -a wikis

  changed_files="$(git -C "${PUBLISH_DIR}" status --porcelain | awk '{print $2}')"
  wikis=()

  [[ "${changed_files}" == *$'\n'docs/claude-code/* || "${changed_files}" == docs/claude-code/* ]] && wikis+=("Claude Code")
  [[ "${changed_files}" == *$'\n'docs/deepagents-wiki/* || "${changed_files}" == docs/deepagents-wiki/* ]] && wikis+=("Deep Agents")
  [[ "${changed_files}" == *$'\n'docs/opencode-wiki/* || "${changed_files}" == docs/opencode-wiki/* ]] && wikis+=("OpenCode")
  [[ "${changed_files}" == *$'\n'docs/openclaw-wiki/* || "${changed_files}" == docs/openclaw-wiki/* ]] && wikis+=("OpenClaw")
  [[ "${changed_files}" == *$'\n'docs/autogen-wiki/* || "${changed_files}" == docs/autogen-wiki/* ]] && wikis+=("AutoGen")

  wiki_count="${#wikis[@]}"
  if [[ "${wiki_count}" -eq 1 ]]; then
    wiki_label="${wikis[1]}"
    printf 'Update %s wiki content' "${wiki_label}"
    return
  fi

  if [[ "${changed_files}" == "mkdocs.yml" ]]; then
    printf 'Update knowledge base site configuration'
    return
  fi

  printf 'Update knowledge base content'
}

push_current_branch() {
  local branch remote_url cred_file existing_helper
  branch="$(git -C "${PUBLISH_DIR}" branch --show-current)"
  remote_url="$(git -C "${PUBLISH_DIR}" remote get-url origin)"

  if [[ -n "${GITHUB_TOKEN:-}" && "${remote_url}" == https://github.com/* ]]; then
    cred_file="${PUBLISH_DIR}/.git/publish-credentials"
    existing_helper="$(git -C "${PUBLISH_DIR}" config --get credential.helper || true)"
    git -C "${PUBLISH_DIR}" config credential.helper "store --file=${cred_file}"
    printf "protocol=https\nhost=github.com\nusername=x-access-token\npassword=%s\n\n" "${GITHUB_TOKEN}" | git -C "${PUBLISH_DIR}" credential approve
    git -C "${PUBLISH_DIR}" push origin "${branch}"
    rm -f "${cred_file}"
    if [[ -n "${existing_helper}" ]]; then
      git -C "${PUBLISH_DIR}" config credential.helper "${existing_helper}"
    else
      git -C "${PUBLISH_DIR}" config --unset credential.helper
    fi
    return
  fi

  git -C "${PUBLISH_DIR}" push origin "${branch}"
}

if [[ -z "${MESSAGE}" ]]; then
  MESSAGE="$(generate_message)"
fi

echo
echo "Commit message: ${MESSAGE}"

if [[ "${DRY_RUN}" -eq 1 || "${NO_COMMIT}" -eq 1 ]]; then
  echo
  echo "Skipping commit/push."
  exit 0
fi

git -C "${PUBLISH_DIR}" add docs mkdocs.yml
if git -C "${PUBLISH_DIR}" diff --cached --quiet; then
  echo
  echo "No staged changes after sync."
  exit 0
fi

git -C "${PUBLISH_DIR}" commit -m "${MESSAGE}"

if [[ "${NO_PUSH}" -eq 1 ]]; then
  echo
  echo "Commit created locally; push skipped."
  exit 0
fi

push_current_branch

echo
echo "Publish sync complete."
