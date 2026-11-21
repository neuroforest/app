import os
from pathlib import Path

import invoke

from neuro.base import NeuroBase, nfx, plugins
from neuro.base.index import KnowledgeIndex, OntologyIndex
from neuro.utils import terminal_components, terminal_style

from tasks.actions import setup
from tasks.components import neurobase, nf_common, nfx as nfx_tasks


@invoke.task(pre=[setup.env])
def index(c, knowledge=""):
    """Show discovered knowledge .nfx files. -k/--knowledge: details for one."""
    roots = plugins.effective_roots()
    idx = KnowledgeIndex(*roots)

    if knowledge:
        onto_idx = OntologyIndex(*roots)
        _index_info(idx, onto_idx, knowledge)
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


@invoke.task(name="import", pre=[setup.env])
def import_(c, knowledge=""):
    """Import knowledge into neurobase non-destructively. -k/--knowledge required.

    Missing ontology dependencies are loaded; ones already present at the right
    version are reused. Knowledge nodes are anchored to a `KnowledgeMetadata`
    node via `DEFINES` edges; re-running prunes file-absent nodes only within
    that anchor's slice.
    """
    if not knowledge:
        print(f"{terminal_style.FAIL} -k/--knowledge required")
        raise SystemExit(1)
    roots = plugins.effective_roots()
    onto_idx = OntologyIndex(*roots)
    know_idx = KnowledgeIndex(*roots)

    path = nf_common.resolve(know_idx, knowledge)
    if not path:
        print(f"{terminal_style.FAIL} Knowledge not found: {knowledge}")
        raise SystemExit(1)

    doc = nfx.read(path)
    name = doc.name or path.stem

    with NeuroBase() as nb:
        with terminal_components.step(name) as status:
            nb.metaontology._import_dependencies(
                doc.dependencies, index=onto_idx,
                on_import=nfx_tasks.make_dep_logger(status),
            )
            # Every nid reachable through the declared deps - so sync_nfx can tell
            # a foreign reference stub (owned by a dependency, e.g. an OntologyNode
            # class the metrics APPLIES_TO) from a node this file owns, and leave
            # the former's properties (like `color`) intact.
            dep_nids = nfx.NfxTree(
                doc, nb.metaontology._resolver(onto_idx),
            ).all_node_nids(scope="dependencies")
            nb.nodes.sync_nfx(path, dependency_nids=dep_nids)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, knowledge=""):
    """Validate knowledge nodes against the loaded ontology. -k: target one file."""
    neurobase.clear(c, confirmed=True)
    roots = plugins.effective_roots()
    know_idx = KnowledgeIndex(*roots)

    targets = nfx_tasks.resolve_target(know_idx, knowledge, kind="Knowledge")

    if not targets:
        print(f"{terminal_style.WARNING} No knowledge .nfx files found.")
        return

    # The knowledge documents of `nfx.test`.
    with NeuroBase() as nb:
        records = nfx_tasks.run_tests(nb, roots, targets)
    nfx_tasks.report_tests(records)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def render(c, knowledge=""):
    """Load knowledge (and its ontology dependencies) into neurobase and print Neo4j browser link. -k: target one file."""
    neurobase.start(c)
    roots = plugins.effective_roots()
    onto_idx = OntologyIndex(*roots)
    know_idx = KnowledgeIndex(*roots)

    targets = nfx_tasks.resolve_target(know_idx, knowledge, kind="Knowledge")

    if not targets:
        print(f"{terminal_style.WARNING} No knowledge .nfx files found.")
        return

    metaontology_nid = nfx.read(onto_idx.metaontology_path).nid
    with NeuroBase() as nb:
        nb.clear(confirm=True)
        imported = set()
        for path in targets:
            doc = nfx.read(path)
            name = doc.name or path.stem
            for dep_path in nfx_tasks.topo_targets(onto_idx, path, metaontology_nid):
                if dep_path in imported:
                    continue
                dep_name = nfx.read(dep_path).name or dep_path.stem
                with terminal_components.step(dep_name):
                    nb.metaontology.import_nfx(dep_path, index=onto_idx)
                imported.add(dep_path)
            with terminal_components.step(name):
                dep_nids = nfx.NfxTree(
                    doc, nb.metaontology._resolver(onto_idx),
                ).all_node_nids(scope="dependencies")
                nb.nodes.sync_nfx(path, dependency_nids=dep_nids)

    nfx_tasks.print_browser_url()
