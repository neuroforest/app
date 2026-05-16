import os
from pathlib import Path

import invoke

from neuro.base import NeuroBase, nfx, schema
from neuro.base.index import KnowledgeIndex, OntologyIndex
from neuro.base.metaontology import OntologyViolations
from neuro.base.ontology import ObjectValidator
from neuro.utils import internal_utils, terminal_components, terminal_style

from tasks.actions import setup
from tasks.components import neurobase, ontology as ontology_tasks


def validate_knowledge(nb, path):
    """Validate knowledge (instance) nodes in an NFX file against the loaded
    ontology, appending per-node violations onto `nb.metaontology.violations`
    so the caller's gating and printing pick them up uniformly. Nodes whose
    labels don't resolve to any known ontology-object subclass are classified
    via `schema.TypeRegistry` and aggregated as undefined property /
    relationship / node types — typo'd type labels fail loudly."""

    class _Node:
        def __init__(self, labels, properties):
            self.labels = labels
            self.properties = properties

    doc = nfx.read(path)
    registry = schema.TypeRegistry(nb)

    edge_map: dict[str, set[str]] = {}
    for rel in doc.relationships:
        edge_map.setdefault(rel["to"], set()).add(rel["type"])

    undefined: dict[str, dict[str, str]] = {"property": {}, "relationship": {}, "node": {}}

    for entry in doc.nodes:
        labels = entry["labels"]
        entry_props = entry.get("properties", {})
        identifier = (
            entry_props.get("identifier")
            or entry_props.get("name")
            or entry_props.get("label")
            or entry["nid"]
        )

        kind = registry.classify_undefined(labels, edge_map.get(entry["nid"], set()))
        if kind is not None:
            type_label = labels[0] if labels else "?"
            undefined[kind].setdefault(type_label, identifier)
            continue

        node_props = {"neuro.id": entry["nid"], **entry_props}
        violations = ObjectValidator(nb, _Node(labels, node_props)).get_violations()
        if violations:
            nb.metaontology.violations.violations.append(
                (identifier, ":".join(labels), violations)
            )

    nb.metaontology.violations.undefined_property_types.extend(sorted(undefined["property"].items()))
    nb.metaontology.violations.undefined_relationship_types.extend(sorted(undefined["relationship"].items()))
    nb.metaontology.violations.undefined_node_types.extend(sorted(undefined["node"].items()))


@invoke.task(pre=[setup.env])
def index(c, knowledge=""):
    """Show discovered knowledge .nfx files. -k/--knowledge: details for one."""
    roots = internal_utils.get_path_list("PLUGINS")
    idx = KnowledgeIndex(*roots)

    if knowledge:
        _index_info(idx, knowledge)
        return

    app_dir = Path(os.environ["APP_DIR"])
    rows = []
    for path in idx.all_targets():
        doc = nfx.read(path)
        try:
            rel = os.path.relpath(path, app_dir)
        except ValueError:
            rel = str(path)
        rows.append((doc.name or path.stem, doc.version, (doc.nid or "")[:8], rel))
    rows.sort(key=lambda r: r[0])
    terminal_components.table(rows, header=("Name", "Version", "NID", "Path"))


def _index_info(idx, name):
    path = idx.resolve(name)
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
    if doc.dependencies:
        print("\nDependencies:")
        for dep_nid, dep_ver in doc.dependencies:
            print(f"  {dep_nid}@{dep_ver}")
    print()


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, knowledge=""):
    """Validate knowledge nodes against the loaded ontology. -k: target one file."""
    neurobase.clear(c, confirmed=True)
    roots = internal_utils.get_path_list("PLUGINS")
    onto_idx = OntologyIndex(*roots)
    know_idx = KnowledgeIndex(*roots)

    if knowledge:
        path = know_idx.resolve(knowledge)
        if not path:
            print(f"{terminal_style.FAIL} Knowledge not found: {knowledge}")
            raise SystemExit(1)
        targets = [path]
    else:
        targets = know_idx.all_targets()

    if not targets:
        print(f"{terminal_style.WARNING} No knowledge .nfx files found.")
        return

    metaontology_nid = nfx.read(onto_idx.metaontology_path).nid
    failed = []
    with NeuroBase() as nb:
        nb.clear(confirm=True)
        imported = set()
        for path in targets:
            doc = nfx.read(path)
            name = doc.name or path.stem
            # `topo_targets` returns metaontology-first transitive ontology
            # deps; the knowledge file's own nid is already filtered out
            # because it's not in OntologyIndex.
            for dep_path in ontology_tasks.topo_targets(onto_idx, path, metaontology_nid):
                if dep_path in imported:
                    continue
                nb.metaontology.import_nfx(dep_path, index=onto_idx)
                imported.add(dep_path)
            nb.metaontology.violations = OntologyViolations()
            validate_knowledge(nb, path)
            violations = list(nb.metaontology.violations.violations)
            if violations:
                print(f"{terminal_style.FAIL} {name}")
                for identifier, labels, v in violations:
                    print(f"  {identifier} ({labels})")
                    print(repr(v))
                failed.append(name)
            else:
                print(f"{terminal_style.SUCCESS} {name}")

    if failed:
        raise SystemExit(1)
