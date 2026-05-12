#!/usr/bin/env python
"""Retrieve neutron-skills content for planning workflows.

This script is intentionally outside ``src/snapwrap`` so planning tooling stays
decoupled from SNAPWrap runtime/package behavior.

Typical usage:
    python scripts/skills_planning.py \
        --query "Plan SNAP reduction artefacts for a DAC run" \
        --repo /SNS/SNAP/shared/Malcolm/code/forks/neutron-skills
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


class SkillsIntegrationError(RuntimeError):
    """Raised when neutron-skills integration prerequisites are not satisfied."""


def _resolve_git_dir(repo_path: Path) -> Path | None:
    dot_git = repo_path / ".git"
    if dot_git.is_dir():
        return dot_git
    if not dot_git.is_file():
        return None

    try:
        text = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    prefix = "gitdir:"
    if not text.lower().startswith(prefix):
        return None

    git_dir_text = text[len(prefix) :].strip()
    git_dir = Path(git_dir_text)
    if not git_dir.is_absolute():
        git_dir = (repo_path / git_dir).resolve()
    return git_dir


def current_git_branch(repo_path: str | Path) -> str | None:
    root = Path(repo_path).expanduser().resolve()
    git_dir = _resolve_git_dir(root)
    if git_dir is None:
        return None

    head_file = git_dir / "HEAD"
    if not head_file.exists():
        return None

    try:
        head = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not head.startswith("ref: "):
        return None

    ref = head[len("ref: ") :].strip()
    if ref.startswith("refs/heads/"):
        return ref.split("refs/heads/", 1)[1]
    return ref.rsplit("/", 1)[-1] if "/" in ref else ref


def ensure_required_branch(
    repo_path: str | Path,
    required_branch: str = "malcolm_skills",
) -> str:
    branch = current_git_branch(repo_path)
    if branch is None:
        raise SkillsIntegrationError(
            f"Could not determine git branch for skills repo at {Path(repo_path)!s}."
        )
    if branch != required_branch:
        raise SkillsIntegrationError(
            f"Skills repo must use branch {required_branch!r}; found {branch!r} at {Path(repo_path)!s}."
        )
    return branch


def _default_repo_path() -> Path | None:
    raw = os.environ.get("SNAPWRAP_NEUTRON_SKILLS_REPO")
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _import_neutron_skills(repo_path: Path | None) -> Any:
    try:
        return importlib.import_module("neutron_skills")
    except ImportError:
        if repo_path is None:
            raise

    src_path = (repo_path / "src").resolve()
    if src_path.is_dir() and str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    return importlib.import_module("neutron_skills")


def _skills_dir_from_repo(repo_path: Path | None) -> Path | None:
    if repo_path is None:
        return None
    candidate = repo_path / "src" / "neutron_skills" / "skills"
    return candidate if candidate.is_dir() else None


def retrieve_planning_skills(
    query: str,
    *,
    repo_path: str | Path | None = None,
    required_branch: str = "malcolm_skills",
    enforce_branch: bool = True,
    method: str = "deterministic",
    top_k: int = 5,
    extra_paths: list[str] | None = None,
) -> list[dict[str, Any]]:
    resolved_repo = Path(repo_path).expanduser().resolve() if repo_path else _default_repo_path()

    if enforce_branch and resolved_repo is not None:
        ensure_required_branch(resolved_repo, required_branch=required_branch)

    try:
        neutron_skills = _import_neutron_skills(resolved_repo)
    except ImportError as exc:
        raise SkillsIntegrationError(
            "neutron_skills could not be imported. Install it in the active Pixi "
            "environment or set SNAPWRAP_NEUTRON_SKILLS_REPO to a local checkout."
        ) from exc

    merged_extra_paths: list[str] = list(extra_paths or [])
    repo_skills_dir = _skills_dir_from_repo(resolved_repo)
    if repo_skills_dir is not None:
        repo_skills_dir_str = str(repo_skills_dir)
        if repo_skills_dir_str not in merged_extra_paths:
            merged_extra_paths.append(repo_skills_dir_str)

    selected = neutron_skills.retrieve(
        query,
        method=method,
        top_k=top_k,
        extra_paths=merged_extra_paths or None,
    )

    normalized: list[dict[str, Any]] = []
    for skill in selected:
        normalized.append(
            {
                "name": getattr(skill, "name", ""),
                "description": getattr(skill, "description", ""),
                "body": getattr(skill, "body", ""),
                "domain": getattr(skill, "domain", ""),
                "path": str(getattr(skill, "path", "")),
                "allowed_tools": list(getattr(skill, "allowed_tools", []) or []),
                "metadata": dict(getattr(skill, "frontmatter", {}) or {}).get("metadata", {}),
            }
        )

    return normalized


def splice_skill_bodies(skills: list[dict[str, Any]]) -> str:
    chunks = [str(s.get("body", "")).strip() for s in skills if s.get("body")]
    return "\n\n".join(c for c in chunks if c)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retrieve neutron-skills for planning context")
    parser.add_argument("--query", required=True, help="Planning query string")
    parser.add_argument("--repo", default=None, help="Local neutron-skills repo path")
    parser.add_argument("--required-branch", default="malcolm_skills")
    parser.add_argument("--method", default="deterministic", choices=["deterministic", "auto", "llm"])
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--extra-path",
        dest="extra_paths",
        action="append",
        default=[],
        help="Additional skill tree root; may be provided multiple times",
    )
    parser.add_argument(
        "--no-enforce-branch",
        action="store_true",
        help="Disable required branch enforcement (not recommended)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of prompt text")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        skills = retrieve_planning_skills(
            args.query,
            repo_path=args.repo,
            required_branch=args.required_branch,
            enforce_branch=not args.no_enforce_branch,
            method=args.method,
            top_k=args.top_k,
            extra_paths=args.extra_paths,
        )
    except SkillsIntegrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"skills": skills}, indent=2))
        return 0

    for skill in skills:
        print(f"- {skill['name']}: {skill['description']}")
    print("\n--- SPLICE ---\n")
    print(splice_skill_bodies(skills))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
