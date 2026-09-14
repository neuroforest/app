import os
from pathlib import Path

import invoke

from neuro.base import NeuroBase, nfx
from neuro.base.index import NfxIndex, OntologyIndex
from neuro.utils import internal_utils, terminal_components, terminal_style

from tasks.actions import setup
from tasks.components import neurobase


def make_dep_logger(status):
    """Return an `on_import(name, imported, depth)` callback that logs each
    dependency once into a `terminal_components.step` status line."""
    seen = set()
    def on_import(dep_name, imported, depth=1):
        if dep_name in seen:
            return
        seen.add(dep_name)
        indent = "  " * depth
        marker = "▸" if imported else "-"
        suffix = "" if imported else " (loaded)"
        status.log(f"{indent}{marker} {dep_name}{suffix}")
    return on_import


def print_import_report(status, report):
    """Log the notable parts of an `import_nfx` report into a step's status
    line. Silent when an import merely rewrote what it declares."""
    if not report:
        return
    for label, claimed_by in report.get("reparented", ()):
        status.log(f"  ↷ {label} → now defined by {', '.join(claimed_by)}")
    for label, edges in report.get("orphaned", ()):
        if edges:
            status.log(f"  {terminal_style.WARN} {label} orphaned, "
                       f"{edges} edge(s) from outside the ontology layer")
        else:
            status.log(f"  · {label} orphaned")
    if report.get("edges_pruned"):
        status.log(f"  − {report['edges_pruned']} edge(s) pruned")


# The one place that says which nodes belong to the ontology layer, shared so
# `print_orphan_hint` and `ontology.prune` can never disagree about what an
# orphan is — they did once, and the hint that tells you to run `prune` was
# blind to exactly the nodes `prune` was.
#
# Every kind the layer stores is an `OntologyObject`: classes are
# `OntologyNode`, relationship types are `OntologyRelationship`, and a property
# is labelled by its *type* — `Uuid`, `String`, `DateTime`, … — which is why an
# enumeration of the first two silently skipped a whole third of the layer.
# Ask the metaontology for the subtree rather than restating it, so a new
# property type is covered the day it is declared. Leaves `orphans` (a list of
# nodes) in scope.
_ORPHAN_SCOPE = """
    MATCH (root:OntologyNode {label: 'OntologyObject'})
    MATCH (kind:OntologyNode)-[:SUBCLASS_OF*0..]->(root)
    WITH collect(DISTINCT kind.label) AS kinds
    MATCH (n) WHERE any(l IN labels(n) WHERE l IN kinds)
      AND NOT (n)<-[:DEFINES]-(:OntologyMetadata)
    WITH collect(n) AS orphans
"""

# Carries the nodes forward rather than re-matching them by nid: an unlabelled
# `MATCH (n {nid: ...})` is a full scan of the base, and once per orphan it cost
# 20s on sbase where the label-scoped pass costs one.
_ORPHANS = _ORPHAN_SCOPE + """
    UNWIND orphans AS n
    RETURN n.nid AS nid, coalesce(n.label, n.nid) AS label,
           labels(n)[0] AS kind
    ORDER BY label
"""

# Same scope, plus the guard that keeps an orphan still wired into the wider
# graph. `o IN orphans` compares nodes, so no second lookup is needed.
_ORPHANS_WITH_EDGES = _ORPHAN_SCOPE + """
    UNWIND orphans AS n
    OPTIONAL MATCH (n)-[r]-(o)
    WHERE NOT any(lbl IN labels(o) WHERE lbl IN
            ['OntologyMetadata', 'KnowledgeMetadata'])
      AND NOT (o)<-[:DEFINES]-(:OntologyMetadata)
      AND NOT o IN orphans
    RETURN n.nid AS nid, coalesce(n.label, n.nid) AS label,
           labels(n)[0] AS kind,
           count(r) AS held, collect(DISTINCT type(r))[0..4] AS rel_types
    ORDER BY label
"""


def orphan_nodes(nb, with_edges=False):
    """Every ontology-layer node no `OntologyMetadata` defines any more.

    `with_edges` adds `held` / `rel_types` — how much of the wider graph still
    reaches the orphan, which is what decides whether it is safe to delete.
    The hint does not need it and does not pay for it.
    """
    return nb.get_data(_ORPHANS_WITH_EDGES if with_edges else _ORPHANS)


def print_orphan_hint(nb):
    """Print the review commands when the graph holds undefined ontology nodes.

    `import_nfx` releases a node it stops declaring rather than deleting it
    (PLAN-2026-143), and logs each one per-file. In a root import those lines
    scroll past inside a long dependency tree, so the run ends with no sign
    that the graph now holds nodes no `.nfx` declares — real drift, invisible.

    Asked of the graph rather than accumulated from the reports: `import_nfx`
    returns a report only for its own file, and surfaces a nested dependency
    import as a name through `on_import`. Reading the returned report would
    therefore miss exactly the common case — a root import whose orphans come
    from a dependency several levels down.

    Detect and print only, like `print_dependant_hint`: `ontology.prune` is
    graph-wide while an import is scoped to one closure, and a withdrawal can
    be in-flight across commits, so the deletion stays a human's call.
    """
    rows = orphan_nodes(nb)
    if not rows:
        return
    labels = [r["label"] for r in rows]
    shown = ", ".join(sorted(set(labels))[:5])
    print(f"\n{terminal_style.WARN} {len(labels)} node(s) no ontology defines "
          f"any more: {shown}{' …' if len(set(labels)) > 5 else ''}")
    print("    ontology.prune             (review)")
    print("    ontology.prune --confirm   (delete the isolated ones)")


def print_dependant_hint(idx, written_nids):
    """Print the re-import commands for ontologies that depend on anything
    written this run and were not themselves written.

    Detect and print only — never re-import them here. Re-importing in the same
    run would let a command aimed at one ontology write to ontologies the user
    never named (PLAN-2026-143 step 3).

    "Not written" is decided by nid, not by which file the operator named: a
    root import writes its whole closure, and a dependency it just imported
    fresh is as written as the target. Excluding only the named path made the
    hint list ontologies the same run had written — a checklist that never
    converged, since each named ontology then pointed back at the other.
    """
    pending = []
    for path in idx.all_targets():
        doc = nfx.read(path)
        if doc.nid in written_nids:
            continue
        if written_nids & set(doc.dep_nids):
            pending.append(doc.name or path.stem)
    if not pending:
        return
    print(f"\n{terminal_style.WARN} Dependents not re-imported:")
    for name in sorted(pending):
        print(f"    ontology.import -o {name}")


def resolve_target(idx, name, kind="Target"):
    """Resolve a single nfx target by name/nid, or return all targets if name is empty."""
    if name:
        path = idx.resolve(name)
        if not path:
            print(f"{terminal_style.FAIL} {kind} not found: {name}")
            raise SystemExit(1)
        return [path]
    return idx.all_targets()


def topo_targets(onto_idx, target_path, metaontology_nid):
    """Topologically ordered ontology paths for a target: metaontology first,
    then transitive deps deps-before-dependents, ending with the target's
    direct ontology ancestors. The target itself is included only if it is an
    ontology (knowledge targets are not in OntologyIndex)."""
    target_doc = nfx.read(target_path)

    def _resolve_doc(nid):
        p = onto_idx.resolve(nid)
        return nfx.read(p) if p else None

    tree = nfx.NfxTree(target_doc, _resolve_doc)
    paths = []
    for nid in tree.topo_order():
        if nid == metaontology_nid:
            continue
        p = onto_idx.resolve(nid)
        if p:
            paths.append(p)
    return [onto_idx.metaontology_path] + paths


def print_browser_url():
    """Print the Neo4j browser URL for the running neurobase."""
    http_port = os.environ["NEO4J_PORT_HTTP"]
    print(f"\n  http://localhost:{http_port}/browser/")


def print_dependencies(idx, doc):
    """Print a resolved Dependencies section for `doc` using `idx` (an
    OntologyIndex) to look up each pinned nid. Knowledge and ontology .nfx
    both pin ontology nids, so the same renderer works for either."""
    if not doc.dependencies:
        return
    print("\nDependencies:")
    for dep_nid, dep_ver in doc.dependencies:
        dep_path = idx.resolve(dep_nid)
        if dep_path:
            dep_doc = nfx.read(dep_path)
            dep_name = dep_doc.name or dep_path.stem
            actual_ver = dep_doc.version or "?"
            if actual_ver == dep_ver:
                print(f"  {terminal_style.SUCCESS} {dep_name}@{dep_ver}")
            else:
                print(f"  {terminal_style.FAIL} {dep_name}@{dep_ver} (found {actual_ver})")
        else:
            print(f"  {terminal_style.FAIL} {dep_nid}@{dep_ver} (not found)")


@invoke.task(pre=[setup.env])
def index(c):
    """Show every discovered .nfx (ontology, knowledge, metaontology) in one table."""
    roots = internal_utils.get_path_list("PLUGINS")
    idx = NfxIndex(*roots)

    app_dir = Path(os.environ["APP_DIR"])
    type_label = {"metaontology": "meta", "ontology": "onto", "knowledge": "know"}
    type_order = {"metaontology": 0, "ontology": 1, "knowledge": 2}
    entries = []
    for path in idx.all_targets():
        doc = nfx.read(path)
        try:
            rel = os.path.relpath(path, app_dir)
        except ValueError:
            rel = str(path)
        entries.append((doc.type, doc.name or path.stem, doc.version, doc.nid, rel))
    entries.sort(key=lambda r: (type_order.get(r[0], 99), r[1]))
    rows = [
        (type_label.get(t, t or "?"), n, v, (nid or "")[:8], p)
        for t, n, v, nid, p in entries
    ]
    terminal_components.table(rows, header=("Type", "Name", "Version", "NID", "Path"))


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def render(c, name=""):
    """Load an .nfx (ontology, knowledge, or metaontology) and its dependencies
    into neurobase and print the Neo4j browser link. Without --name, renders
    every discovered .nfx. Knowledge targets pull their ontology deps from
    OntologyIndex."""
    neurobase.start(c)
    roots = internal_utils.get_path_list("PLUGINS")
    nfx_idx = NfxIndex(*roots)
    onto_idx = OntologyIndex(*roots)

    targets = resolve_target(nfx_idx, name, kind="Nfx")
    if not targets:
        print(f"{terminal_style.WARN} No .nfx files found.")
        return

    metaontology_nid = nfx.read(onto_idx.metaontology_path).nid
    with NeuroBase() as nb:
        nb.clear(confirm=True)
        imported = set()
        for path in targets:
            doc = nfx.read(path)
            target_name = doc.name or path.stem
            if doc.type == "knowledge":
                for dep_path in topo_targets(onto_idx, path, metaontology_nid):
                    if dep_path in imported:
                        continue
                    dep_name = nfx.read(dep_path).name or dep_path.stem
                    with terminal_components.step(dep_name):
                        nb.metaontology.import_nfx(dep_path, index=onto_idx)
                    imported.add(dep_path)
                with terminal_components.step(target_name):
                    nb.nodes.import_nfx(path)
                imported.add(path)
            else:
                if path in imported:
                    continue
                with terminal_components.step(target_name):
                    nb.metaontology.import_nfx(path, index=onto_idx)
                imported.add(path)

    print_browser_url()
