"""
Show branch and sync status for all submodules.
"""

import json
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


def get_head(path):
    """Get HEAD commit hash."""
    result = subprocess.run(
        ["git", "-C", path, "rev-parse", "HEAD"],
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


def get_ahead_count(path, ref):
    """Count commits in HEAD that are not in ref."""
    result = subprocess.run(
        ["git", "-C", path, "rev-list", f"{ref}..HEAD", "--count"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    return int(result.stdout.strip())


@invoke.task(pre=[setup.env])
def status(c):
    """Show branch and sync status for all submodules."""
    submodules = parse_gitmodules()
    local_subs = json.loads(os.environ.get("SUBMODULES", "{}"))
    max_path = max(len(path) for path, _ in submodules) if submodules else 0

    for path, expected in submodules:
        if not os.path.isdir(path):
            print(f"{terminal_style.FAIL} {path:<{max_path}}  (not initialized)")
            continue

        current = get_branch(path)
        if current is None:
            print(f"{terminal_style.FAIL} {path:<{max_path}}  (detached HEAD)")
            continue

        issues = []

        if current != expected:
            issues.append(f"expected {expected}")

        behind = get_behind_count(path, expected)
        if behind is None:
            issues.append("no remote tracking")
        elif behind > 0:
            issues.append(f"{behind} behind")

        source = local_subs.get(path)
        if source:
            app_head = get_head(path)
            if app_head:
                unsynced = get_ahead_count(source, app_head)
                if unsynced and unsynced > 0:
                    issues.append(f"{unsynced} not synced")

            unpushed = get_ahead_count(source, f"origin/{expected}")
            if unpushed and unpushed > 0:
                issues.append(f"{unpushed} unpushed")

        if issues:
            symbol = terminal_style.FAIL if current != expected else terminal_style.WARN
            print(f"{symbol} {path:<{max_path}}  {current} ({', '.join(issues)})")
        else:
            print(f"{terminal_style.SUCCESS} {path:<{max_path}}  {current} (up to date)")
