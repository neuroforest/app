"""`invoke nf.*` - the `.nf` roots an environment reads.

A root is opted in by listing it in `PLUGINS` of the environment, nothing
else; `nf.roots` shows what that list comes to on this machine - which
entries exist, which are the consolidated `.nf` layout, which sit in a git
repo (hooks and tags live there; a root outside one gets neither), and how
many modules each contributes.
"""
import os
import subprocess
from pathlib import Path

import invoke

from neuro.base import plugins
from neuro.base.index import NfxIndex
from neuro.utils import internal_utils, terminal_components, terminal_style

from tasks.actions import setup


def _git_toplevel(path):
    try:
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


@invoke.task(pre=[setup.env])
def roots(c):
    """Show the PLUGINS roots in effect: layout, git repo, module count; missing entries flagged."""
    present = plugins.effective_roots()
    missing = internal_utils.missing_path_list("PLUGINS")
    idx = NfxIndex(*present)
    counts = {}
    for entry in idx.entries():
        counts[entry.registry_root] = counts.get(entry.registry_root, 0) + 1

    app_dir = Path(os.environ["APP_DIR"])
    rows = []
    for root in present:
        try:
            shown = os.path.relpath(root, app_dir)
        except ValueError:
            shown = str(root)
        layout = ".nf" if plugins.is_consolidated(root) else "legacy"
        top = _git_toplevel(root)
        repo = os.path.relpath(top, app_dir) if top else f"{terminal_style.WARN} none"
        rows.append((shown, layout, repo, str(counts.get(root, 0))))
    for p in missing:
        rows.append((f"{terminal_style.WARN} {p}", "missing", "-", "-"))

    print(f"PLUGINS={os.environ.get('PLUGINS', '')}")
    terminal_components.table(rows, header=("Root", "Layout", "Repo", "Modules"))
    if missing:
        print(f"\n{len(missing)} listed root(s) absent on this machine - skipped, not fatal")
