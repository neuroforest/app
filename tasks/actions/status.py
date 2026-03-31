"""
Show branch and sync status for all submodules.
"""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

import invoke

from tasks.actions import setup
from neuro.utils import build_utils, terminal_style


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


def fetch(path):
    """Fetch origin for a repo."""
    subprocess.run(
        ["git", "-C", path, "fetch", "--quiet", "origin"],
        capture_output=build_utils.quiet()
    )


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


def get_recorded_commit(path):
    """Get the commit hash the parent repo has recorded for a submodule."""
    result = subprocess.run(
        ["git", "ls-tree", "HEAD", path],
        capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    # format: "<mode> commit <hash>\t<path>"
    parts = result.stdout.strip().split()
    if len(parts) >= 3:
        return parts[2]
    return None


def has_uncommitted_changes(path):
    """Check if a repository has uncommitted changes (staged, unstaged, or untracked)."""
    result = subprocess.run(
        ["git", "-C", path, "status", "--porcelain"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def get_worktree_path(submodule_path):
    """Get the develop worktree path for an owned submodule."""
    result = subprocess.run(
        ["git", "-C", submodule_path, "worktree", "list", "--porcelain"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    current_path = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line.removeprefix("worktree ")
        elif line == "branch refs/heads/develop":
            return current_path
    return None


@invoke.task(pre=[setup.env])
def status(c):
    """Show branch and sync status for all submodules."""
    submodules = parse_gitmodules()

    fetch_paths = set()
    for path, _ in submodules:
        if os.path.isdir(path):
            fetch_paths.add(path)

    with terminal_style.step("Fetch"):
        with ThreadPoolExecutor() as pool:
            pool.map(fetch, fetch_paths)

    max_path = max(len(path) for path, _ in submodules) if submodules else 0
    ok_count = 0

    for path, expected in submodules:
        if not os.path.isdir(path):
            print(f"{terminal_style.FAIL} {path:<{max_path}}  (not initialized)")
            continue

        is_worktree = path in setup.OWNED_SUBMODULES
        if is_worktree:
            wt_path = get_worktree_path(path)
            current = get_branch(wt_path) if wt_path else get_branch(path)
        else:
            current = get_branch(path)
        issues = []

        if current is None:
            issues.append("detached HEAD")
        elif current != expected:
            issues.append(f"expected {expected}")

        behind = get_behind_count(path, expected)
        if behind is None:
            issues.append("no remote tracking")
        elif behind > 0:
            issues.append(f"{behind} behind")

        recorded = get_recorded_commit(path)
        head = get_head(path)
        if recorded and head and recorded != head:
            issues.append("pointer not committed")

        if is_worktree:
            if wt_path and has_uncommitted_changes(wt_path):
                issues.append("uncommitted")
            if head:
                result = subprocess.run(
                    ["git", "-C", path, "rev-list", f"HEAD..{expected}", "--count"],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    wt_ahead = int(result.stdout.strip())
                    if wt_ahead > 0:
                        issues.append(f"worktree {wt_ahead} ahead")

        if issues:
            unexpected_branch = current is not None and current != expected
            symbol = terminal_style.FAIL if unexpected_branch else terminal_style.WARN
            print(f"{symbol} {path:<{max_path}}  {current or 'HEAD'} ({', '.join(issues)})")
        else:
            ok_count += 1

    # Check app (current repo) itself
    issues = []
    current = get_branch(".")
    if current is None:
        issues.append("detached HEAD")
    result = subprocess.run(
        ["git", "status", "--porcelain", "--ignore-submodules=dirty"],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        issues.append("uncommitted")
    ahead = get_ahead_count(".", f"origin/{current}") if current else None
    if ahead and ahead > 0:
        issues.append(f"{ahead} unpushed")
    if issues:
        print(f"{terminal_style.WARN} {'app':<{max_path}}  {current or 'HEAD'} ({', '.join(issues)})")
    else:
        ok_count += 1

    if ok_count == len(submodules) + 1:
        print(f"{terminal_style.SUCCESS} All {ok_count} modules up to date")
    elif ok_count > 0:
        print(f"{terminal_style.SUCCESS} {ok_count} other modules up to date")
