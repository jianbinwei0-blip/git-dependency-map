#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple


@dataclass(frozen=True)
class RepoNode:
    name: str
    path: str
    full_name: Optional[str]
    owner: Optional[str]


RG_EXCLUDES = [
    "!.git",
    "!node_modules",
    "!dist",
    "!build",
    "!target",
    "!venv",
    "!.venv",
]

DEPENDENCY_REL_TYPES = {
    "go_module",
    "node_dependency",
    "python_dependency",
    "git_submodule",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a heuristic cross-repo dependency map from local clones.",
    )
    parser.add_argument("--repos-root", required=True, help="Directory containing cloned repos.")
    parser.add_argument("--org", help="GitHub org for owner/repo shorthand matching (e.g. example-org).")
    parser.add_argument(
        "--repo-list-file",
        help="Optional file with owner/repo lines to restrict the repo set.",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory (default: <repos-root>/_dependency_map).",
    )
    parser.add_argument(
        "--max-evidence-per-edge",
        type=int,
        default=5,
        help="Max evidence snippets kept per edge (default: 5).",
    )
    return parser.parse_args()


def parse_repo_ref(value: str) -> Optional[Tuple[str, str]]:
    raw = value.strip()
    if not raw or raw.startswith("#"):
        return None

    http_match = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", raw)
    if http_match:
        return http_match.group(1), http_match.group(2)

    ssh_match = re.match(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", raw)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    bare_match = re.match(r"^([^/\s]+)/([^/\s]+)$", raw)
    if bare_match:
        return bare_match.group(1), bare_match.group(2).removesuffix(".git")

    return None


def discover_repo_dirs(root: Path) -> List[Path]:
    return sorted(
        [p for p in root.iterdir() if p.is_dir() and (p / ".git").is_dir()],
        key=lambda p: p.name.lower(),
    )


def parse_origin_full_name(repo_dir: Path) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None

    if proc.returncode != 0:
        return None

    url = proc.stdout.strip()
    parsed = parse_repo_ref(url)
    if not parsed:
        return None
    owner, repo = parsed
    return f"{owner}/{repo}"


def load_allowed_repo_names(repo_list_file: Path) -> set[str]:
    allowed: set[str] = set()
    for line in repo_list_file.read_text(encoding="utf-8").splitlines():
        parsed = parse_repo_ref(line)
        if parsed:
            allowed.add(parsed[1])
    return allowed


def classify_relation_type(relative_path: str) -> str:
    rel = relative_path.replace("\\", "/")
    base = rel.split("/")[-1]

    if base == "go.mod":
        return "go_module"
    if base in {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}:
        return "node_dependency"
    if base in {"requirements.txt", "pyproject.toml", "poetry.lock", "Pipfile", "Pipfile.lock"}:
        return "python_dependency"
    if base == ".gitmodules":
        return "git_submodule"
    if rel.startswith(".github/workflows/"):
        return "github_action"
    if base in {"Dockerfile", "docker-compose.yaml", "docker-compose.yml"}:
        return "container_reference"
    return "reference"


def chunked(items: Sequence[str], chunk_size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), chunk_size):
        yield list(items[i : i + chunk_size])


def collect_go_module_aliases(
    repo_dirs: Sequence[Path],
    known_repo_names: Set[str],
) -> Dict[str, Set[str]]:
    """
    Build repo-name -> module-path aliases from go.mod declarations.

    This bridges common mismatches where GitHub repo is "transform" but code
    references the module path "internal.example.net/transform".
    """
    aliases: Dict[str, Set[str]] = defaultdict(set)
    module_line_re = re.compile(r"^\s*module\s+([^\s]+)\s*$")
    semver_suffix_re = re.compile(r"^v\d+$")

    for repo_dir in repo_dirs:
        for go_mod in repo_dir.rglob("go.mod"):
            try:
                content = go_mod.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            module_path: Optional[str] = None
            for line in content.splitlines():
                m = module_line_re.match(line)
                if m:
                    module_path = m.group(1).strip()
                    break

            if not module_path:
                continue

            parts = [part for part in module_path.split("/") if part]
            if not parts:
                continue

            repo_name: Optional[str] = None
            if parts[-1] in known_repo_names:
                repo_name = parts[-1]
            elif (
                len(parts) >= 2
                and semver_suffix_re.fullmatch(parts[-1])
                and parts[-2] in known_repo_names
            ):
                # Module path like example.com/pkg/repo/v2 maps to repo "repo".
                repo_name = parts[-2]

            if repo_name:
                aliases[repo_name].add(module_path)

    return dict(aliases)


def build_patterns(
    repo_names: Sequence[str],
    org: Optional[str],
    module_aliases: Optional[Dict[str, Set[str]]] = None,
) -> List[str]:
    escaped = [re.escape(name) for name in sorted(repo_names, key=len, reverse=True)]
    alt = "|".join(escaped)
    if not alt:
        return []

    patterns = [rf"github\.com[:/][A-Za-z0-9_.-]+/({alt})(?:\.git)?"]
    if org:
        org_escaped = re.escape(org)
        patterns.append(rf"\b{org_escaped}/({alt})(?:@[\w.\-]+)?\b")

    alias_values: List[str] = []
    if module_aliases:
        for repo in repo_names:
            for alias in sorted(module_aliases.get(repo, set())):
                alias_values.append(alias)
    if alias_values:
        alias_alt = "|".join(re.escape(alias) for alias in sorted(set(alias_values), key=len, reverse=True))
        patterns.append(rf"\b(?:{alias_alt})(?:@[\w.\-]+)?\b")

    return patterns


def build_extractors(
    repo_names: Sequence[str],
    org: Optional[str],
    module_aliases: Optional[Dict[str, Set[str]]] = None,
) -> List[Tuple[re.Pattern[str], Optional[Dict[str, str]]]]:
    escaped = [re.escape(name) for name in sorted(repo_names, key=len, reverse=True)]
    alt = "|".join(escaped)
    if not alt:
        return []

    extractors: List[Tuple[re.Pattern[str], Optional[Dict[str, str]]]] = [
        re.compile(
            rf"github\.com[:/](?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>{alt})(?:\.git)?",
            re.IGNORECASE,
        ),
    ]
    extractors = [(extractors[0], None)]
    if org:
        org_escaped = re.escape(org)
        extractors.append((
            re.compile(rf"\b{org_escaped}/(?P<repo>{alt})(?:@[\w.\-]+)?\b", re.IGNORECASE)
        , None))

    alias_to_repo: Dict[str, str] = {}
    alias_values: List[str] = []
    if module_aliases:
        for repo in repo_names:
            for alias in sorted(module_aliases.get(repo, set())):
                alias_values.append(alias)
                alias_to_repo[alias.lower()] = repo

    if alias_values:
        alias_alt = "|".join(re.escape(alias) for alias in sorted(set(alias_values), key=len, reverse=True))
        alias_pattern = re.compile(rf"\b(?P<alias>{alias_alt})(?:@[\w.\-]+)?\b", re.IGNORECASE)
        extractors.append((alias_pattern, alias_to_repo))

    return extractors


def iter_rg_matches(repo_dir: Path, patterns: Sequence[str]) -> Iterator[Tuple[str, int, str]]:
    if not patterns:
        return

    cmd = ["rg", "--json", "-n", "-I", "-S", "--hidden"]
    for glob in RG_EXCLUDES:
        cmd.extend(["-g", glob])
    for pattern in patterns:
        cmd.extend(["-e", pattern])
    cmd.append(".")

    proc = subprocess.run(
        cmd,
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )

    if proc.returncode not in (0, 1):
        raise RuntimeError(f"rg failed in {repo_dir}: {proc.stderr.strip()}")

    for raw in proc.stdout.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data", {})
        path_obj = data.get("path", {})
        lines_obj = data.get("lines", {})
        path = path_obj.get("text", "")
        line_no = int(data.get("line_number", 0) or 0)
        text = str(lines_obj.get("text", "")).rstrip("\n")
        if path:
            yield path, line_no, text


def extract_targets(
    line: str,
    extractors: Sequence[Tuple[re.Pattern[str], Optional[Dict[str, str]]]],
    known_repo_names: set[str],
) -> List[Tuple[str, Optional[str]]]:
    owners_by_repo: Dict[str, Optional[str]] = {}
    for extractor, alias_to_repo in extractors:
        for match in extractor.finditer(line):
            owner: Optional[str] = None
            repo: Optional[str]

            if alias_to_repo is None:
                repo = match.groupdict().get("repo")
                owner = match.groupdict().get("owner")
            else:
                alias = match.groupdict().get("alias")
                repo = alias_to_repo.get(alias.lower()) if alias else None

            if not repo:
                continue
            if repo in known_repo_names:
                existing_owner = owners_by_repo.get(repo)
                # Prefer a concrete owner over None if both patterns match.
                if existing_owner is None and owner is not None:
                    owners_by_repo[repo] = owner
                elif repo not in owners_by_repo:
                    owners_by_repo[repo] = owner
    return sorted(owners_by_repo.items(), key=lambda item: item[0])


def sanitize_mermaid_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"r_{cleaned}"
    return cleaned


def main() -> int:
    args = parse_args()

    repos_root = Path(args.repos_root).expanduser().resolve()
    if not repos_root.is_dir():
        print(f"repos root not found: {repos_root}", file=sys.stderr)
        return 1

    repo_dirs = discover_repo_dirs(repos_root)
    if not repo_dirs:
        print(f"no git repos found under: {repos_root}", file=sys.stderr)
        return 1

    if args.repo_list_file:
        repo_list_file = Path(args.repo_list_file).expanduser().resolve()
        if not repo_list_file.is_file():
            print(f"repo list file not found: {repo_list_file}", file=sys.stderr)
            return 1
        allowed = load_allowed_repo_names(repo_list_file)
        if allowed:
            repo_dirs = [d for d in repo_dirs if d.name in allowed]
        if not repo_dirs:
            print("repo list file did not match any local repos.", file=sys.stderr)
            return 1

    nodes: List[RepoNode] = []
    known_repo_names = {d.name for d in repo_dirs}
    for repo_dir in repo_dirs:
        full_name = parse_origin_full_name(repo_dir)
        owner = full_name.split("/")[0] if full_name and "/" in full_name else None
        nodes.append(
            RepoNode(
                name=repo_dir.name,
                path=str(repo_dir),
                full_name=full_name,
                owner=owner,
            )
        )

    go_module_aliases = collect_go_module_aliases(repo_dirs, known_repo_names)

    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else repos_root / "_dependency_map"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    edges: Dict[Tuple[str, str], Dict[str, object]] = {}
    chunk_size = 120

    for source_dir in repo_dirs:
        source = source_dir.name
        repo_name_chunks = list(chunked(sorted(known_repo_names), chunk_size))
        for name_chunk in repo_name_chunks:
            patterns = build_patterns(name_chunk, args.org, go_module_aliases)
            extractors = build_extractors(name_chunk, args.org, go_module_aliases)
            if not patterns:
                continue

            for file_path, line_no, line in iter_rg_matches(source_dir, patterns):
                matches = extract_targets(line, extractors, known_repo_names)
                if not matches:
                    continue

                relation_type = classify_relation_type(file_path)
                snippet = line.strip()
                if len(snippet) > 220:
                    snippet = snippet[:217] + "..."

                for target, owner in matches:
                    if target == source:
                        continue

                    key = (source, target)
                    edge = edges.get(key)
                    if edge is None:
                        edge = {
                            "source": source,
                            "target": target,
                            "occurrences": 0,
                            "relation_type_counts": defaultdict(int),
                            "owners_observed": set(),
                            "evidence": [],
                        }
                        edges[key] = edge

                    edge["occurrences"] = int(edge["occurrences"]) + 1
                    rtc = edge["relation_type_counts"]
                    assert isinstance(rtc, defaultdict)
                    rtc[relation_type] += 1

                    owners_observed = edge["owners_observed"]
                    assert isinstance(owners_observed, set)
                    if owner:
                        owners_observed.add(owner)

                    evidence = edge["evidence"]
                    assert isinstance(evidence, list)
                    if len(evidence) < args.max_evidence_per_edge:
                        evidence.append(
                            {
                                "file": file_path,
                                "line": line_no,
                                "relation_type": relation_type,
                                "snippet": snippet,
                            }
                        )

    edge_list = []
    for (_, _), edge in sorted(edges.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        relation_type_counts = dict(sorted(edge["relation_type_counts"].items()))
        dependency_occurrences = sum(
            count for rel_type, count in relation_type_counts.items() if rel_type in DEPENDENCY_REL_TYPES
        )
        owners_observed = sorted(edge["owners_observed"])
        evidence = edge["evidence"]
        edge_list.append(
            {
                "source": edge["source"],
                "target": edge["target"],
                "occurrences": edge["occurrences"],
                "dependency_occurrences": dependency_occurrences,
                "relation_type_counts": relation_type_counts,
                "owners_observed": owners_observed,
                "evidence": evidence,
            }
        )

    edges_json_path = output_dir / "edges.json"
    edges_json_path.write_text(
        json.dumps(
            {
                "repos_root": str(repos_root),
                "org": args.org,
                "node_count": len(nodes),
                "edge_count": len(edge_list),
                "nodes": [node.__dict__ for node in nodes],
                "edges": edge_list,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    edges_csv_path = output_dir / "edges.csv"
    with edges_csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "source",
                "target",
                "occurrences",
                "dependency_occurrences",
                "relation_types",
                "evidence_files",
            ]
        )
        for edge in edge_list:
            relation_types = ";".join(
                f"{k}:{v}" for k, v in edge["relation_type_counts"].items()
            )
            evidence_files = sorted({ev["file"] for ev in edge["evidence"]})
            writer.writerow(
                [
                    edge["source"],
                    edge["target"],
                    edge["occurrences"],
                    edge["dependency_occurrences"],
                    relation_types,
                    ";".join(evidence_files),
                ]
            )

    mermaid_path = output_dir / "dependency-map.mmd"
    lines = ["graph LR"]

    for node in sorted(nodes, key=lambda n: n.name.lower()):
        node_id = sanitize_mermaid_id(node.name)
        lines.append(f'  {node_id}["{node.name}"]')

    if edge_list:
        for edge in edge_list:
            sid = sanitize_mermaid_id(edge["source"])
            tid = sanitize_mermaid_id(edge["target"])
            type_label = ",".join(
                f"{k}:{v}" for k, v in edge["relation_type_counts"].items()
            )
            lines.append(f'  {sid} -->|{type_label}| {tid}')
    else:
        lines.append("  %% No cross-repo edges found")

    mermaid_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Repos analyzed: {len(nodes)}")
    print(f"Edges found:    {len(edge_list)}")
    print(f"JSON:           {edges_json_path}")
    print(f"CSV:            {edges_csv_path}")
    print(f"Mermaid:        {mermaid_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
