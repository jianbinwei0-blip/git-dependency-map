#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  sync_github_repos.sh --org <org> --dest <repos_dir> [--limit 200]
  sync_github_repos.sh --repos-file <repos.txt> --dest <repos_dir>

Description:
  Discover GitHub repositories from an organization or a repos file, then
  clone missing repos and update existing local clones.

Options:
  --org <org>             GitHub organization name (for discovery).
  --repos-file <path>     File with one repo reference per line:
                          - owner/repo
                          - https://github.com/owner/repo
                          - git@github.com:owner/repo.git
  --dest <path>           Destination directory where repos are synced.
  --limit <n>             Max repos for org discovery (default: 200).
  -h, --help              Show help.
EOF
}

ORG=""
REPOS_FILE=""
DEST=""
LIMIT=200

normalize_repo_ref() {
  local raw="$1"
  local value
  value="$(printf '%s' "$raw" | sed -E 's/#.*$//; s/^[[:space:]]+//; s/[[:space:]]+$//')"
  [[ -z "$value" ]] && return 1

  if [[ "$value" =~ ^https?://github\.com/([^/]+)/([^/]+?)(\.git)?/?$ ]]; then
    printf '%s/%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    return 0
  fi

  if [[ "$value" =~ ^git@github\.com:([^/]+)/([^/]+?)(\.git)?$ ]]; then
    printf '%s/%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    return 0
  fi

  if [[ "$value" =~ ^[^/[:space:]]+/[^/[:space:]]+$ ]]; then
    printf '%s\n' "${value%.git}"
    return 0
  fi

  return 1
}

discover_org_repos() {
  local org="$1"
  local limit="$2"

  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    gh repo list "$org" --limit "$limit" --json nameWithOwner -q '.[].nameWithOwner'
    return
  fi

  if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required for GitHub API fallback discovery." >&2
    exit 1
  fi

  local page=1
  local per_page=100
  local fetched=0

  while (( fetched < limit )); do
    local url="https://api.github.com/orgs/${org}/repos?per_page=${per_page}&page=${page}"
    local response
    if ! response="$(curl -fsSL "$url")"; then
      echo "Failed to query GitHub API at page ${page}: ${url}" >&2
      break
    fi

    local count
    count="$(printf '%s' "$response" | jq 'length')"
    if [[ "$count" -eq 0 ]]; then
      break
    fi

    printf '%s' "$response" | jq -r '.[].full_name'
    fetched=$(( fetched + count ))
    page=$(( page + 1 ))
  done | head -n "$limit"
}

discover_file_repos() {
  while IFS= read -r line || [[ -n "$line" ]]; do
    if normalize_repo_ref "$line"; then
      continue
    fi
  done < "$REPOS_FILE"
}

sync_repo() {
  local full_name="$1"
  local repo_name="${full_name##*/}"
  local repo_dir="${DEST}/${repo_name}"

  if [[ -d "${repo_dir}/.git" ]]; then
    git -C "$repo_dir" remote set-url origin "https://github.com/${full_name}.git" >/dev/null 2>&1 || true
    git -C "$repo_dir" remote update --prune >/dev/null 2>&1
    echo "updated  ${full_name}"
    return 0
  fi

  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    gh repo clone "$full_name" "$repo_dir" -- --quiet >/dev/null 2>&1
  else
    git clone --quiet "https://github.com/${full_name}.git" "$repo_dir" >/dev/null 2>&1
  fi

  echo "cloned   ${full_name}"
  return 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --org)
      ORG="${2:-}"
      shift 2
      ;;
    --repos-file)
      REPOS_FILE="${2:-}"
      shift 2
      ;;
    --dest)
      DEST="${2:-}"
      shift 2
      ;;
    --limit)
      LIMIT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$DEST" ]]; then
  echo "--dest is required." >&2
  usage
  exit 1
fi

if [[ -z "$ORG" && -z "$REPOS_FILE" ]]; then
  echo "Provide either --org or --repos-file." >&2
  usage
  exit 1
fi

if [[ -n "$ORG" && -n "$REPOS_FILE" ]]; then
  echo "Use either --org or --repos-file, not both." >&2
  usage
  exit 1
fi

if [[ -n "$REPOS_FILE" && ! -f "$REPOS_FILE" ]]; then
  echo "Repos file not found: $REPOS_FILE" >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required." >&2
  exit 1
fi

mkdir -p "$DEST"
tmp_list="$(mktemp)"
trap 'rm -f "$tmp_list"' EXIT

if [[ -n "$ORG" ]]; then
  discover_org_repos "$ORG" "$LIMIT" > "$tmp_list"
else
  discover_file_repos > "$tmp_list"
fi

sort -u "$tmp_list" -o "$tmp_list"

if [[ ! -s "$tmp_list" ]]; then
  echo "No repositories discovered." >&2
  exit 1
fi

repo_list_file="${DEST}/.repo-list.txt"
> "$repo_list_file"

success_count=0
fail_count=0

while IFS= read -r repo || [[ -n "$repo" ]]; do
  [[ -z "$repo" ]] && continue
  if sync_repo "$repo"; then
    echo "$repo" >> "$repo_list_file"
    success_count=$(( success_count + 1 ))
  else
    echo "failed   ${repo}" >&2
    fail_count=$(( fail_count + 1 ))
  fi
done < "$tmp_list"

if [[ "$success_count" -eq 0 ]]; then
  echo "Failed to sync all repositories." >&2
  exit 1
fi

echo
echo "Synced repositories: ${success_count}"
echo "Failed repositories: ${fail_count}"
echo "Repo list: ${repo_list_file}"
