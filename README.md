# github-repo-dependency-map

Codex skill for building cross-repository dependency maps from GitHub repositories.

It can:
- sync repositories from a GitHub org or a curated repo list
- optionally index each repo with GitNexus
- generate cross-repo dependency outputs (`JSON`, `CSV`, `Mermaid`)
- resolve Go module alias mismatches (for example `internal.example.net/transform` -> repo `transform`)

## Repository Layout

- `SKILL.md`: skill instructions and usage
- `agents/openai.yaml`: metadata for skill UIs
- `scripts/`: executable workflow scripts
- `references/`: heuristics and behavior notes

## Requirements

- `git`, `jq`, `rg`, `python3`
- `gh` (optional, but recommended for org discovery/private repos)
- `npx` + `gitnexus` (optional, only for indexing step)

## Quick Usage (scripts)

```bash
./scripts/run_full_workflow.sh --org example-org --dest /tmp/example-org-repo-map --limit 300
```

Focus on one repo target (example: `transform`):

```bash
awk -F, 'NR==1 || ($2=="transform" && $4+0>0)' /tmp/example-org-repo-map/_dependency_map/edges.csv
```

## Install as a Codex skill

Clone this repo, then place/symlink it under your Codex skills directory, for example:

```bash
mkdir -p ~/.codex/skills
git clone <your-repo-url> ~/.codex/skills/github-repo-dependency-map
```

## License

MIT
