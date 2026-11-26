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
    """The hooks column: `global` (the machine's global nf check judges every tree), else the tree's own -
    `current`, `stale` (reinstall with `tree.hooks`), `none` - or `-` where no tree's repository is."""
    if not plugins.is_consolidated(root):
        return "-"
    try:
        state = nf_repo.Repo(root).hooks_state()
    except (ValueError, RuntimeError):
        return "-"
    return f"{terminal_style.WARN} stale" if state == "stale" else state


def _version(root):
    """The version of the tree's namespace declaration, `-` where it has none to read."""
    try:
        return nf_trees.declared(root).version or "-"
    except nf_trees.RegistryError:
        return "-"


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
    """List the trees on this machine: namespace token and version, module count, hooks, whether this environment may load it, whether it is registered, absolute path."""
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
        rows.append((label, _version(root) if present else "-", str(count) if present else "-",
                     _hooks(root) if present else "-", "✔" if loaded else "", registry, str(root)))
    terminal_components.table(rows, header=("Namespace", "Version", "Modules", "Hooks", "Scope", "Registry", "Path"))
    for entry in plugins.missing_roots():
        print(f"{terminal_style.WARN} {entry} is listed in PLUGINS but names nothing here - skipped, not fatal")
    if any("outdated" in r[5] for r in rows):
        print(f"{terminal_style.WARN} a registry line no longer matches its tree's declaration - `tree.register --tree <path>`")
    for root, loaded, line in forest:
        if loaded and line is None and plugins.is_consolidated(root) and not _of_checkout(root):
            print(f"{terminal_style.DIM}{root} is in scope by path only - `tree.register --tree {root}` "
                  f"records it{terminal_style.RESET}")


def _of_checkout(root):
    """A tree that belongs to a checkout of the app - its own `.nf` or a fixtures' tree under it."""
    return Path(os.environ["APP_DIR"]).resolve() in root.parents


_INDEX_KINDS = {"": None, "ontology": {"metaontology", "ontology"}, "knowledge": {"knowledge"}}


def print_index(namespace="", scope=False, kind=""):
    """The body of `nf.index`, callable from the per-kind shortcuts
    (`ontology.index`, `knowledge.index`)."""
    if kind not in _INDEX_KINDS:
        print(f"{terminal_style.FAIL} --kind is `ontology` or `knowledge`, not {kind!r}")
        raise SystemExit(1)
    types = _INDEX_KINDS[kind]
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
        if (want and typed != want) or (types and entry.type not in types):
            continue
        if entry.registry_root in outside:
            ns = f"{ns} {terminal_style.DIM}(out of scope){terminal_style.RESET}"
        entries.append((entry.type, entry.name or entry.path.stem, entry.version, entry.nid, ns))
    if want and want not in seen:
        print(f"{terminal_style.FAIL} no namespace {namespace!r} - known: {', '.join(sorted(seen))}")
        raise SystemExit(1)
    entries.sort(key=lambda r: (type_order.get(r[0], 99), r[1].casefold()))
    # a column that would say the same on every row is left out
    typed_column, ns_column = not types or len(types) > 1, not want
    rows = [(*((type_label.get(t, t or "?"),) if typed_column else ()), n, v, (nid or "")[:8],
             *((ns,) if ns_column else ())) for t, n, v, nid, ns in entries]
    header = (*(("Type",) if typed_column else ()), "Name", "Version", "NID", *(("Namespace",) if ns_column else ()))
    terminal_components.table(rows, header=header)


@invoke.task(pre=[setup.env], help={
    "namespace": "Only this namespace's documents (`root` or `·` for the empty token)",
    "scope": "Only the trees this environment may load (its PLUGINS)",
    "kind": "`ontology` (the metaontology with them) or `knowledge`: only that kind's documents",
})
def index(c, namespace="", scope=False, kind=""):
    """Show every discovered .nfx (ontology, knowledge, metaontology) in one table;
    --namespace narrows to one tree, --scope to what this environment loads, --kind to one kind."""
    print_index(namespace, scope, kind)
