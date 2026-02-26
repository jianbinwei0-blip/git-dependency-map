---
name: github-repo-dependency-map
description: Use when you need to discover GitHub repos (org or custom list), clone or update them locally, optionally index each repo with GitNexus, and generate a cross-repo dependency map for architecture analysis or migration planning.
---

# GitHub Repo Dependency Map

## Overview

Build a repeatable workflow for repository-dependency visualization across any public GitHub organization or custom repo set. Use bundled scripts to sync repos, run GitNexus indexing per repo, and export a cross-repo map as JSON, CSV, and Mermaid.

## Workflow

1. Sync repositories locally:
```bash
./scripts/sync_github_repos.sh --org <org> --dest <repos_dir> [--limit 200]
```
or:
```bash
./scripts/sync_github_repos.sh --repos-file <repos.txt> --dest <repos_dir>
```

2. Optionally index each repo with GitNexus:
```bash
./scripts/index_with_gitnexus.sh --repos-root <repos_dir> [--force] [--embeddings]
```

3. Build cross-repo dependency map:
```bash
python3 ./scripts/build_cross_repo_map.py \
  --repos-root <repos_dir> \
  [--org <org>] \
  --output-dir <repos_dir>/_dependency_map
```

4. Or run all of the above in one command:
```bash
./scripts/run_full_workflow.sh --org <org> --dest <repos_dir> --index
```
or:
```bash
./scripts/run_full_workflow.sh --repos-file <repos.txt> --dest <repos_dir> --index
```

## Quick Examples

Generate map for a public org, no indexing:
```bash
./scripts/run_full_workflow.sh \
  --org example-org \
  --dest ~/work/example-org-repos \
  --limit 100
```

Generate map for curated repos and include GitNexus indexing:
```bash
cat > /tmp/repos.txt <<'EOF'
openai/openai-cookbook
anthropics/anthropic-cookbook
https://github.com/modelcontextprotocol/servers
EOF

./scripts/run_full_workflow.sh \
  --repos-file /tmp/repos.txt \
  --dest ~/work/public-repo-set \
  --index \
  --embeddings
```

## Outputs

- `<repos_dir>/.repo-list.txt`: Synced `owner/repo` list
- `<repos_dir>/_dependency_map/edges.json`: Structured edge data and evidence
- `<repos_dir>/_dependency_map/edges.csv`: Flat edge table (includes `dependency_occurrences`)
- `<repos_dir>/_dependency_map/dependency-map.mmd`: Mermaid graph

## Interpretation Notes

- GitNexus indexing remains per-repo. This skill adds a separate cross-repo map layer.
- Cross-repo edges are heuristic (pattern-based), not full semantic resolution.
- Go module aliases are resolved from local `go.mod` declarations (for example, `internal.example.net/transform` -> repo `transform`).
- Prefer edges where `dependency_occurrences > 0` when answering “which repos depend on X”.
- Treat map output as directional evidence for architecture review, then validate critical edges manually.

## Prerequisites

- `git`, `jq`, `rg`, `python3`
- `gh` for private repos or easier org listing (optional for public repos)
- `npx` + `gitnexus` only if using indexing scripts

## Troubleshooting

- `gh auth status` fails:
  Use a PAT with `gh auth login`, or use `--repos-file` with public URLs.
- `jq` or `rg` missing:
  Install via package manager before running scripts.
- No edges found:
  Confirm repo set has cross references, and pass `--org` when repos belong to one org.

## References

- Read `references/map-heuristics.md` when refining detection logic.
