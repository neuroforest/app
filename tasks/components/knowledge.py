import os
from pathlib import Path

import invoke

from neuro.base import NeuroBase, nfx, plugins
from neuro.base.index import KnowledgeIndex, NfxIndex
from neuro.utils import terminal_components, terminal_style

from tasks.actions import setup
from tasks.components import neurobase, nf_common, nfx as nfx_tasks


@invoke.task(pre=[setup.env])
def index(c, knowledge=""):
    """Show discovered knowledge .nfx files. -k/--knowledge: details for one."""
    roots = plugins.effective_roots()
    idx = KnowledgeIndex(*roots)

    if knowledge:
        # every type: a knowledge module may pin another
        _index_info(idx, NfxIndex(*roots), knowledge)
        return

    app_dir = Path(os.environ["APP_DIR"])
    rows = []
    for entry in idx.entries():
        path = entry.path
        try:
            rel = os.path.relpath(path, app_dir)
        except ValueError:
            rel = str(path)
        rows.append((
            entry.name or path.stem, entry.version, (entry.nid or "")[:8],
            nf_common.namespace_label(idx, entry.registry_root), rel,
        ))
    rows.sort(key=lambda r: r[0].casefold())
    terminal_components.table(rows, header=("Name", "Version", "NID", "Namespace", "Path"))


def _index_info(idx, onto_idx, name):
    path = nf_common.resolve(idx, name)
    if not path:
        print(f"{terminal_style.FAIL} Knowledge not found: {name}")
        raise SystemExit(1)

    doc = nfx.read(path)
    B, RST, DIM = terminal_style.BOLD, terminal_style.RESET, terminal_style.DIM
    print(f"\n{B}{doc.name or path.stem}{RST} {DIM}v{doc.version or '?'}{RST}")
    print("-" * 50)
    if doc.description:
        print(f"  {doc.description}")
    print(f"  {DIM}{doc.nid or '?'}{RST}")
    print(f"  {DIM}{path}{RST}")
    print(f"\nNodes: {len(doc.nodes)}")
    print(f"Relationships: {len(doc.relationships)}")
    nfx_tasks.print_dependencies(onto_idx, doc)
    print()


@invoke.task(pre=[setup.env])
def info(c, tree=False):
    """Shortcut for `nfx.info --kind knowledge`: the knowledge modules loaded in the
    base, not on disk. --tree: their dependency graph, ontologies included."""
    with NeuroBase() as nb:
        nfx_tasks.print_info(nb, kind="knowledge", tree=tree)


@invoke.task(name="import", pre=[setup.env])
def import_(c, knowledge=""):
    """Import knowledge into neurobase non-destructively. -k/--knowledge required.

    Missing dependencies are loaded - ontologies and pinned knowledge modules
    alike, transitively; ones already present at the right version are reused.
    Knowledge nodes are anchored to a `KnowledgeMetadata` node via `DEFINES`
    edges; re-running prunes file-absent nodes only within that anchor's slice.
    """
    if not knowledge:
        print(f"{terminal_style.FAIL} -k/--knowledge required")
        raise SystemExit(1)
    roots = plugins.effective_roots()
    idx = NfxIndex(*roots)

    path = nf_common.resolve(KnowledgeIndex(*roots), knowledge)
    if not path:
        print(f"{terminal_style.FAIL} Knowledge not found: {knowledge}")
        raise SystemExit(1)

    doc = nfx.read(path)
    name = doc.name or path.stem

    with NeuroBase() as nb:
        with terminal_components.step(name) as status:
            nb.metaontology._import_dependencies(
                doc.dependencies, index=idx,
                on_import=nfx_tasks.make_dep_logger(status),
            )
            # Every nid reachable through the declared deps - so sync_nfx can tell
            # a foreign reference stub (owned by a dependency, e.g. an OntologyNode
            # class the metrics APPLIES_TO, or a node of a pinned knowledge module)
            # from a node this file owns, and leave the former's properties (like
            # `color`) intact.
            dep_nids = nfx.NfxTree(
                doc, nb.metaontology._resolver(idx),
            ).all_node_nids(scope="dependencies")
            nb.nodes.sync_nfx(path, dependency_nids=dep_nids, index=idx)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, knowledge=""):
    """Shortcut for `nfx.test --kind knowledge`. -k: target one file."""
    nfx_tasks.run_test_task(c, target=knowledge, kind="knowledge")


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def render(c, knowledge=""):
    """Load knowledge and its dependency closure - the ontologies and the knowledge
    modules it pins - into neurobase and print Neo4j browser link. -k: target one file."""
    neurobase.start(c)
    roots = plugins.effective_roots()
    idx = NfxIndex(*roots)

    targets = nfx_tasks.resolve_target(KnowledgeIndex(*roots), knowledge, kind="Knowledge")

    if not targets:
        print(f"{terminal_style.WARNING} No knowledge .nfx files found.")
        return

    with NeuroBase() as nb:
        nb.clear(confirm=True)
        loaded = set()
        for path in targets:
            nfx_tasks.load_closure(nb, idx, path, loaded)

    nfx_tasks.print_browser_url()
