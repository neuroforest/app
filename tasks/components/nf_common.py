"""What the `nf.*`, `tree.*` and `nfx.*` tasks share.

The three collections are named for what a task acts on - the forest, one
`.nf` tree, one module - and this is the common ground under them: how a tree
or a module named on the command line is found, how a refusal is printed, and
the release gate that runs `nfx.test` in the test base.
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

from neuro.base import nf_repo, nfx, plugins
from neuro.base.index import NfxIndex
from neuro.utils import terminal_components, terminal_style

from tasks.actions import setup


ROOT_MARK = f"{terminal_style.DIM}·{terminal_style.RESET}"
ROOT_WORDS = ("root", "·")  # how the empty token is typed

# The environment the wrapper started this process with, before any `setup.env`
# loaded a config into it: what a child run in another ENV must start from, or
# it would inherit this one's base and trees.
STARTED_WITH = dict(os.environ)


def namespace_label(idx, root):
    """The token column for the tree at `root`: the declared token, a dim `·`
    for the written empty token (the root namespace, `~/.nf`), `-` for a legacy
    root, a warning for a `.nf` tree that has not declared one yet."""
    ns = idx.namespace_of(root)
    if ns is not None:
        return ns.token or ROOT_MARK
    return f"{terminal_style.WARN} none" if plugins.is_consolidated(root) else "-"


def key(target):
    """A module is named by stem, name or nid - and a file path
    (`knowledge/stains.nfx`, absolute or not) names the module of that stem."""
    target = target.strip()
    return Path(target).stem if target.endswith(".nfx") else target


def caller_tree():
    """The tree the task was called from. `setup.env` changes into APP_DIR, but
    the shell's `PWD` still names where the caller stood; the tree is that
    directory or the nearest parent holding a namespace declaration."""
    here = Path(os.environ.get("PWD") or ".").expanduser()
    for d in (here, *here.parents):
        if (d / nfx.NAMESPACE_FILENAME).is_file():
            return d
    raise SystemExit(f"{terminal_style.FAIL} {here}: not inside a .nf tree - pass --tree")


def tree_path(tree):
    """A tree is named by its path or by its namespace token (`root` or `·`:
    the empty one), the token looked up among this environment's trees."""
    path = Path(tree).expanduser()
    if path.exists():
        return path
    want = "" if tree in ROOT_WORDS else tree
    roots = plugins.effective_roots()
    idx = NfxIndex(*roots)
    found = [r for r in roots if (ns := idx.namespace_of(r)) is not None and (ns.token or "") == want]
    if len(found) != 1:
        raise SystemExit(f"{terminal_style.FAIL} {tree}: neither a path nor the token of a tree in PLUGINS")
    return Path(found[0])


def repo(tree=""):
    """The repository of `tree` (a path or a token), or of the tree the caller stands in."""
    try:
        return nf_repo.Repo(tree_path(tree) if tree else caller_tree())
    except (ValueError, RuntimeError) as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")


def owner_tree(module):
    """The tree among PLUGINS that holds the module `module` names."""
    roots = plugins.effective_roots()
    path = NfxIndex(*roots).resolve(module)
    root = path and plugins.registry_root_of(path, roots)
    if root is None:
        raise SystemExit(f"{terminal_style.FAIL} {module}: in none of the PLUGINS trees - pass --tree")
    return root


def refused(what, issues):
    print(f"{terminal_style.FAIL} {terminal_style.BOLD}{what} refused{terminal_style.RESET} - nothing written:")
    for issue in issues:
        print(f"    {issue}")
    raise SystemExit(1)


def test_gate(repo, roots):
    """The gate of a release: `nfx.test` over the documents about to
    be committed, run as a child in ENV=TESTING - its base is wiped, so it must
    never be this process's - reading this release's trees, not TESTING's."""
    roots = [*repo._others(roots, repo.root), repo.root]

    def gate(paths):
        return nfx_test(roots, paths, lambda path: repo.show(Path(path).relative_to(repo.root)))

    return gate


def nfx_test(roots, paths=None, show=str):
    """Run `nfx.test` as a child in ENV=TESTING over `roots` (`paths`: only
    these documents) and return its failures as issue lines. The child starts
    from the wrapper's own environment, so the base it wipes is the test one."""
    env = {k: v for k, v in STARTED_WITH.items() if k not in ("NF_CONFIG", "NF_DATA", "NF_STATE", "NF_CACHE")}
    env["ENV"] = "TESTING"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "records.json"
        target = ["--target", ",".join(str(p) for p in paths)] if paths else []
        what = f"{len(paths)} document(s)" if paths else "every document"
        with terminal_components.step(f"Testing {what} in the test base"):
            r = subprocess.run(
                [os.path.join(setup.get_nenv_dir(), "bin", "invoke"), f"--search-root={os.environ['APP_DIR']}",
                 "nfx.test", *target, "--trees", ":".join(str(p) for p in roots), "--out", str(out)],
                env=env, capture_output=True, text=True)
        if not out.is_file():
            tail = (r.stdout + r.stderr).strip().splitlines()[-8:]
            return ["the tests could not run (--no-test skips them):", *tail]
        issues = []
        for record in json.loads(out.read_text()):
            where = show(record["path"])
            for failure in record["failures"]:
                lines = failure.splitlines() or [""]
                issues.append(f"{where}: {lines[0]}")
                issues += [f"    {line}" for line in lines[1:]]
        return issues
