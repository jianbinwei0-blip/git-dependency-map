# Cross-Repo Map Heuristics

This skill builds cross-repo edges from textual evidence, not from full semantic linking.

## Edge Detection Inputs

- `go.mod` -> `go_module`
- `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock` -> `node_dependency`
- `requirements.txt`, `pyproject.toml`, `poetry.lock`, `Pipfile`, `Pipfile.lock` -> `python_dependency`
- `.gitmodules` -> `git_submodule`
- `.github/workflows/*` -> `github_action`
- `Dockerfile`, `docker-compose.yaml`, `docker-compose.yml` -> `container_reference`
- everything else -> `reference`

## Match Patterns

- `github.com/owner/repo` and `github.com:owner/repo`
- If `--org` is provided, also match shorthand `org/repo` (useful for GitHub Actions and import paths)
- Go module alias resolution from local `go.mod` declarations:
  - Detect module paths where last segment maps to a known repo name.
  - Example: repo `transform` with module `internal.example.net/transform`.
  - Then match those aliases in `require` and import references.

## Limitations

- Shorthand `org/repo` matching may include a small number of false positives.
- Package manager indirection (aliases, mirrors, internal registries) may hide true dependencies.
- Repo-name overlap across owners can be ambiguous when `--org` is not provided.

## Refinement Strategy

1. Run with `--org` whenever possible.
2. Start with `edges.csv`, then inspect `edges.json` evidence snippets for high-impact edges.
3. Validate critical edges manually before migration or breaking change decisions.
4. Use `dependency_occurrences` in `edges.csv` / `edges.json` to prioritize likely real dependency edges over generic references.
