import invoke

from neuro.base import NeuroBase, nfx, plugins
from neuro.base.index import KnowledgeIndex, NfxIndex
from neuro.utils import terminal_components, terminal_style

from tasks.actions import setup
from tasks.components import neurobase, nf as nf_tasks, nf_common, nfx as nfx_tasks


@invoke.task(pre=[setup.env])
def index(c, knowledge=""):
    """Shortcut for `nf.index --kind knowledge --scope`: the knowledge modules this environment loads. -k/--knowledge: details of one."""
    if knowledge:
        roots = plugins.effective_roots()
        # every type: a knowledge module may pin another
        _index_info(KnowledgeIndex(*roots), NfxIndex(*roots), knowledge)
        return
    nf_tasks.print_index(scope=True, kind="knowledge")


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
def info(c):
    """Shortcut for `nfx.info --kind knowledge`: the knowledge modules loaded in the
    base, not on disk."""
    with NeuroBase() as nb:
        nfx_tasks.print_info(nb, kind="knowledge")


@invoke.task(name="import", pre=[setup.env])
def import_(c, knowledge=""):
    """Import knowledge into neurobase non-destructively. -k/--knowledge required.

    Missing dependencies are loaded - ontologies and pinned knowledge modules
    alike, transitively; ones already present at the right version are reused.
    Knowledge nodes are anchored to a `KnowledgeMetadata` node via `DEFINES`
    edges; a node the file stops declaring is released, and deleted only when
    nothing is left on it.
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
            report = nb.nodes.sync_nfx(path, dependency_nids=dep_nids, index=idx)
            nfx_tasks.print_import_report(status, report)


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
