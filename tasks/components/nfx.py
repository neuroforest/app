import os
from pathlib import Path

import invoke

from neuro.base import NeuroBase, nfx
from neuro.base.index import NfxIndex, OntologyIndex
from neuro.utils import internal_utils, terminal_components, terminal_style

from tasks.actions import setup
from tasks.components import neurobase


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
        print(f"{terminal_style.WARNING} No .nfx files found.")
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
