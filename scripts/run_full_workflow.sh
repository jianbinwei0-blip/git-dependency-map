#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run_full_workflow.sh --org <org> --dest <repos_dir> [--limit 200] [--index] [--force] [--embeddings]
  run_full_workflow.sh --repos-file <repos.txt> --dest <repos_dir> [--index] [--force] [--embeddings]

Description:
  Orchestrate full workflow: sync repos, optional GitNexus indexing, then
  generate cross-repo dependency map.
EOF
}

ORG=""
REPOS_FILE=""
DEST=""
LIMIT=200
DO_INDEX=0
FORCE=0
EMBEDDINGS=0

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
    --index)
      DO_INDEX=1
      shift
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

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

sync_cmd=("$SCRIPT_DIR/sync_github_repos.sh" "--dest" "$DEST")
if [[ -n "$ORG" ]]; then
  sync_cmd+=("--org" "$ORG" "--limit" "$LIMIT")
else
  sync_cmd+=("--repos-file" "$REPOS_FILE")
fi

echo "==> Sync repositories"
"${sync_cmd[@]}"

if (( DO_INDEX == 1 )); then
  echo "==> Index with GitNexus"
  index_cmd=("$SCRIPT_DIR/index_with_gitnexus.sh" "--repos-root" "$DEST")
  (( FORCE == 1 )) && index_cmd+=("--force")
  (( EMBEDDINGS == 1 )) && index_cmd+=("--embeddings")
  "${index_cmd[@]}"
fi

echo "==> Build cross-repo dependency map"
map_cmd=(
  "python3"
  "$SCRIPT_DIR/build_cross_repo_map.py"
  "--repos-root" "$DEST"
  "--repo-list-file" "$DEST/.repo-list.txt"
  "--output-dir" "$DEST/_dependency_map"
)
if [[ -n "$ORG" ]]; then
  map_cmd+=("--org" "$ORG")
fi
"${map_cmd[@]}"

echo
echo "Done. Outputs:"
echo "  $DEST/_dependency_map/edges.json"
echo "  $DEST/_dependency_map/edges.csv"
echo "  $DEST/_dependency_map/dependency-map.mmd"
