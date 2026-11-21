"""`nf.*` - the forest: every `.nf` tree this environment reads.

A forest task takes no address and writes nothing; it reports. One tree is
`tree.*`, one module is `nfx.*`.

A tree is opted in by listing it in `PLUGINS` of the environment, nothing
else; `nf.trees` shows what that list comes to on this machine - the namespace
token each tree declares (a dim `·` is the written empty
token, a legacy root has none), how many modules it contributes, the state of
its hooks, its absolute path, and any listed entry that is absent.
"""
from pathlib import Path

import invoke

from neuro.base import nf_repo, plugins
from neuro.base.index import NfxIndex
from neuro.utils import internal_utils, terminal_components, terminal_style

from tasks.actions import setup
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


@invoke.task(pre=[setup.env])
def trees(c):
    """List the trees in effect: namespace token, module count, hooks, absolute path.
    A `PLUGINS` entry absent on this machine is skipped by every task; it is named here."""
    present = plugins.effective_roots()
    idx = NfxIndex(*present)
    counts = {}
    for entry in idx.entries():
        counts[entry.registry_root] = counts.get(entry.registry_root, 0) + 1
    rows = [(namespace_label(idx, root), str(counts.get(root, 0)), _hooks(root), str(Path(root).resolve()))
            for root in present]
    terminal_components.table(rows, header=("Namespace", "Modules", "Hooks", "Path"))
    for p in internal_utils.missing_path_list("PLUGINS"):
        print(f"{terminal_style.WARN} {p} is listed in PLUGINS but absent - skipped, not fatal")


@invoke.task(pre=[setup.env], help={
    "namespace": "Only this namespace's documents (`root` or `·` for the empty token)",
})
def index(c, namespace=""):
    """Show every discovered .nfx (ontology, knowledge, metaontology) in one table;
    --namespace narrows to one tree."""
    roots = plugins.effective_roots()
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
