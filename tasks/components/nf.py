"""`nf.*` - the forest: every `.nf` tree on this machine.

A forest task takes no address and writes nothing; it reports. One tree is
`tree.*`, one module is `nfx.*`.

Two lists meet here. The **registry** (`~/.config/neuroforest/trees.toml`,
`neuro.base.nf_trees`) names every tree on the machine, whatever environment
is running. **`PLUGINS`** is the scope of the current environment: the trees
it may load - by path, or as `@<token>` of a registered tree. `nf.trees` and
`nf.index` show both and mark what is in scope; `--scope` narrows to it. The
app's own tree (`<app>/.nf`) and a test fixtures' tree belong to a checkout,
not to the machine, so they are in scope by path and in no registry.
"""
import os
from pathlib import Path

import invoke

from neuro.base import nf_repo, nf_trees, plugins
from neuro.base.index import NfxIndex
from neuro.utils import exceptions, terminal_components, terminal_style

from tasks.actions import setup
from tasks.components import nf_common
from tasks.components.nf_common import ROOT_MARK, ROOT_WORDS, namespace_label


def _hooks(root):
    """The hooks column: `current`, `stale` (reinstall with `tree.hooks`), `none`, or `-` where no tree's repository is."""
    if not plugins.is_consolidated(root):
        return "-"
    try:
        state = nf_repo.Repo(root).hooks_state()
    except (ValueError, RuntimeError):
        return "-"
    return f"{terminal_style.WARN} stale" if state == "stale" else state


def _forest(scope_only=False):
    """The trees to show, as `(root, in scope, registry line or None)`: this
    environment's scope in its order, then the registered trees outside it."""
    in_scope = plugins.effective_roots()
    by_path = {t.path.resolve(): t for t in nf_common.registered()}
    rows = [(root, True, by_path.pop(root, None)) for root in in_scope]
    if not scope_only:
        rows += [(path, False, t) for path, t in by_path.items()]
    return rows


@invoke.task(pre=[setup.env], help={"scope": "Only the trees this environment may load (its PLUGINS)"})
def trees(c, scope=False):
    """List the trees on this machine: namespace token, module count, hooks, whether this environment may load it, whether it is registered, absolute path."""
    forest = _forest(scope)
    idx = NfxIndex(*(root for root, loaded, _ in forest if loaded))
    rows = []
    for root, loaded, line in forest:
        label = namespace_label(idx, root) if loaded else line.token or ROOT_MARK
        present = loaded or line.present
        count = sum(1 for _ in plugins.walk_plugins([root])) if present else 0
        if line is None:
            registry = "-"
        elif not present:
            registry = f"{terminal_style.WARN} absent"
        else:
            live = nf_trees.declared(root)
            registry = "✔" if (live.nid, live.namespace or "") == (line.nid, line.token) else f"{terminal_style.WARN} outdated"
        rows.append((label, str(count) if present else "-", _hooks(root) if present else "-",
                     "✔" if loaded else "", registry, str(root)))
    terminal_components.table(rows, header=("Namespace", "Modules", "Hooks", "Scope", "Registry", "Path"))
    for entry in plugins.missing_roots():
        print(f"{terminal_style.WARN} {entry} is listed in PLUGINS but names nothing here - skipped, not fatal")
    if any("outdated" in r[4] for r in rows):
        print(f"{terminal_style.WARN} a registry line no longer matches its tree's declaration - `tree.register --tree <path>`")
    for root, loaded, line in forest:
        if loaded and line is None and plugins.is_consolidated(root) and not _of_checkout(root):
            print(f"{terminal_style.DIM}{root} is in scope by path only - `tree.register --tree {root}` "
                  f"records it{terminal_style.RESET}")


def _of_checkout(root):
    """A tree that belongs to a checkout of the app - its own `.nf` or a fixtures' tree under it."""
    return Path(os.environ["APP_DIR"]).resolve() in root.parents


@invoke.task(pre=[setup.env], help={
    "namespace": "Only this namespace's documents (`root` or `·` for the empty token)",
    "scope": "Only the trees this environment may load (its PLUGINS)",
})
def index(c, namespace="", scope=False):
    """Show every discovered .nfx (ontology, knowledge, metaontology) in one table;
    --namespace narrows to one tree, --scope to what this environment loads."""
    forest = _forest(scope)
    outside = {root for root, loaded, line in forest if not loaded and line.present}
    roots = [root for root, loaded, line in forest if loaded or line.present]
    try:
        idx = NfxIndex(*roots)
    except exceptions.NfxViolation as e:
        if not outside:
            raise
        print(f"{terminal_style.WARN} the trees outside this environment's scope do not index together with it "
              f"({e}) - showing the scope only")
        outside, roots = set(), [root for root, loaded, _ in forest if loaded]
        idx = NfxIndex(*roots)
    want = "root" if namespace in ROOT_WORDS else namespace

    type_label = {"metaontology": "meta", "ontology": "onto", "knowledge": "know"}
    type_order = {"metaontology": 0, "ontology": 1, "knowledge": 2}
    entries = []
    seen = set()
    for entry in idx.entries():
        ns = namespace_label(idx, entry.registry_root)
        typed = "root" if ns == ROOT_MARK else ns
        seen.add(typed)
        if want and typed != want:
            continue
        if entry.registry_root in outside:
            ns = f"{ns} {terminal_style.DIM}(out of scope){terminal_style.RESET}"
        entries.append((entry.type, entry.name or entry.path.stem, entry.version, entry.nid, ns))
    if want and not entries:
        print(f"{terminal_style.FAIL} no namespace {namespace!r} - known: {', '.join(sorted(seen))}")
        raise SystemExit(1)
    entries.sort(key=lambda r: (type_order.get(r[0], 99), r[1].casefold()))
    if want:
        rows = [(type_label.get(t, t or "?"), n, v, (nid or "")[:8]) for t, n, v, nid, _ in entries]
        terminal_components.table(rows, header=("Type", "Name", "Version", "NID"))
    else:
        rows = [(type_label.get(t, t or "?"), n, v, (nid or "")[:8], ns) for t, n, v, nid, ns in entries]
        terminal_components.table(rows, header=("Type", "Name", "Version", "NID", "Namespace"))
