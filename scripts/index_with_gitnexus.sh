#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  index_with_gitnexus.sh --repos-root <repos_dir> [--force] [--embeddings]

Description:
  Run GitNexus indexing for every git repository under the given root.

Options:
  --repos-root <path>  Directory containing cloned repositories.
  --force              Force full re-index.
  --embeddings         Enable embeddings during analyze.
  -h, --help           Show help.
EOF
}

REPOS_ROOT=""
FORCE=0
EMBEDDINGS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repos-root)
      REPOS_ROOT="${2:-}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --embeddings)
      EMBEDDINGS=1
      shift
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

if [[ -z "$REPOS_ROOT" ]]; then
  echo "--repos-root is required." >&2
  usage
  exit 1
fi

if [[ ! -d "$REPOS_ROOT" ]]; then
  echo "Directory not found: $REPOS_ROOT" >&2
  exit 1
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "npx is required." >&2
  exit 1
fi

success=0
failed=0

while IFS= read -r repo_dir || [[ -n "$repo_dir" ]]; do
  [[ -z "$repo_dir" ]] && continue
  [[ ! -d "$repo_dir/.git" ]] && continue

  cmd=(npx -y gitnexus@latest analyze)
  (( FORCE == 1 )) && cmd+=(--force)
  (( EMBEDDINGS == 1 )) && cmd+=(--embeddings)
  cmd+=("$repo_dir")

  echo "indexing $(basename "$repo_dir") ..."
  if "${cmd[@]}"; then
    success=$(( success + 1 ))
  else
    echo "failed   $(basename "$repo_dir")" >&2
    failed=$(( failed + 1 ))
  fi
done < <(find "$REPOS_ROOT" -mindepth 1 -maxdepth 1 -type d | sort)

echo
echo "Indexed repositories: ${success}"
echo "Failed repositories:  ${failed}"

if [[ "$failed" -gt 0 ]]; then
  exit 1
fi
