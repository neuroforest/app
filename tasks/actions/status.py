"""
Show branch and sync status for all submodules.
"""

import os
import subprocess

import invoke

from tasks.actions import setup
from neuro.utils import terminal_style


def parse_gitmodules():
    """Parse .gitmodules into list of (path, branch) tuples."""
    result = subprocess.run(
        ["git", "config", "--file", ".gitmodules", "--list"],
        capture_output=True, text=True, check=True
    )
    entries = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        parts = key.split(".")
        if len(parts) < 3 or parts[0] != "submodule":
            continue
        name = ".".join(parts[1:-1])
        field = parts[-1]
        entries.setdefault(name, {})[field] = value
    return [
        (fields.get("path", name), fields["branch"])
        for name, fields in entries.items()
    ]


def get_branch(path):
    """Get current branch, or None if detached."""
    result = subprocess.run(
        ["git", "-C", path, "symbolic-ref", "--short", "HEAD"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def get_behind_count(path, branch):
    """Count commits HEAD is behind origin/{branch}."""
    result = subprocess.run(
        ["git", "-C", path, "rev-list", f"HEAD..origin/{branch}", "--count"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    return int(result.stdout.strip())


@invoke.task(pre=[setup.env])
def status(c):
    """Show branch and sync status for all submodules."""
    submodules = parse_gitmodules()
    max_path = max(len(path) for path, _ in submodules) if submodules else 0

    for path, expected in submodules:
        if not os.path.isdir(path):
            print(f"{terminal_style.FAIL} {path:<{max_path}}  (not initialized)")
            continue

        current = get_branch(path)
        if current is None:
            print(f"{terminal_style.FAIL} {path:<{max_path}}  (detached HEAD)")
            continue

        wrong_branch = current != expected
        behind = get_behind_count(path, expected)

        if wrong_branch:
            symbol = terminal_style.FAIL
            detail = f"{current} (expected {expected})"
        elif behind is None:
            symbol = terminal_style.WARN
            detail = f"{current} (no remote tracking)"
        elif behind > 0:
            symbol = terminal_style.WARN
            detail = f"{current} ({behind} behind)"
        else:
            symbol = terminal_style.SUCCESS
            detail = f"{current} (up to date)"

        print(f"{symbol} {path:<{max_path}}  {detail}")
