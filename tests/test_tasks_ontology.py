"""Integration tests for `nde ontology.render`.

Tasks are invoked in-process via `__wrapped__` and assertions run against
real NeuroBase state. The source of truth for expected counts is the .nfx
file itself, so the tests stay valid as long as render correctly imports
what's declared.
"""
from invoke import MockContext

from neuro.base import nfx
from neuro.utils.internal_utils import get_path
from tasks.components.ontology import render

METAONTOLOGY_PATH = get_path("assets") / "ontology" / "metaontology.nfx"


def test_render(nb):
    render.__wrapped__(MockContext(), ontology="Metaontology")

    names = nb.get_data('MATCH (m:OntologyMetadata) RETURN m.name AS name')
    assert {r["name"] for r in names} == {"Metaontology"}


def test_render_node_count(nb):
    render.__wrapped__(MockContext(), ontology="Metaontology")
    assert nb.count() == len(nfx.read(METAONTOLOGY_PATH).nodes) + 1


def test_render_bare(nb):
    render.__wrapped__(MockContext(), ontology="Metaontology", bare=True)

    leftover = nb.get_data("""
        MATCH (or:OntologyRelationship)-[:SUBCLASS_OF*0..]->(:OntologyRelationship {label: "HAS_PROPERTY"})
        MATCH ()-[r]->(p) WHERE type(r) = or.label
        RETURN count(DISTINCT p) AS c
    """)[0]["c"]
    assert leftover == 0


def test_prune(nb):
    """Only orphans holding no outside relationship are deleted."""
    from tasks.components.ontology import prune

    render.__wrapped__(MockContext(), ontology="Metaontology")
    nb.run_query("""
        CREATE (isolated:OntologyNode {nid: 'prune-isolated', label: 'Isolated'})
        CREATE (held:OntologyNode {nid: 'prune-held', label: 'Held'})
        CREATE (page:EntityPage {nid: 'prune-page', label: 'Page'})
        CREATE (page)-[:RENDERS]->(held)
    """)

    prune.__wrapped__(MockContext(), confirm=True)

    remaining = {r["nid"] for r in nb.get_data(
        "MATCH (n) WHERE n.nid IN ['prune-isolated', 'prune-held'] RETURN n.nid AS nid"
    )}
    assert remaining == {"prune-held"}


def test_document_failures(tmp_path):
    """Duplicates are reported from the document, before an import could MERGE them away."""
    import json
    import uuid
    from types import SimpleNamespace

    from tasks.components.ontology import _document_failures

    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    rel = {"from": a, "to": b, "type": "USES"}
    data = {"type": "ontology", "nid": str(uuid.uuid4()), "version": "1.0",
            "nodes": [{"nid": a}, {"nid": b}, {"nid": b}], "relationships": [rel, rel]}
    path = tmp_path / "dup.nfx"
    path.write_text(json.dumps(data))
    idx = SimpleNamespace(resolve=lambda key: None)

    assert _document_failures(idx, path) == [f"duplicate node nid {b}", f"duplicate USES {a} → {b}"]

    data["nodes"], data["relationships"] = [{"nid": a}, {"nid": b}], [rel]
    path.write_text(json.dumps(data))
    assert _document_failures(idx, path) == []


def test_print_dependant_hint(tmp_path, capsys):
    """A dependency the same run imported fresh is written, so it is not pending."""
    import json
    import subprocess
    from types import SimpleNamespace

    from tasks.components import nfx as nfx_tasks

    def uuid4():
        return subprocess.run(["uuidgen"], capture_output=True, text=True).stdout.strip()

    root, mid, leaf, outside = uuid4(), uuid4(), uuid4(), uuid4()

    def write(name, nid, deps):
        path = tmp_path / f"{name}.nfx"
        path.write_text(json.dumps({
            "type": "ontology", "nid": nid, "version": "1.0", "name": name,
            "dependencies": [f"{d}@1.0" for d in deps], "nodes": [],
        }))
        return path

    paths = [write("root", root, [mid]), write("mid", mid, [leaf]),
             write("leaf", leaf, []), write("outside", outside, [leaf])]
    idx = SimpleNamespace(all_targets=lambda: paths)

    # Importing root writes mid and leaf too. `mid` depends on written `leaf`,
    # but is itself written — naming it would be a re-import of what just ran.
    nfx_tasks.print_dependant_hint(idx, {root, mid, leaf})
    out = capsys.readouterr().out
    assert "ontology.import -o outside" in out
    assert "-o mid" not in out and "-o root" not in out

    # Importing the whole closure leaves nothing pending.
    nfx_tasks.print_dependant_hint(idx, {root, mid, leaf, outside})
    assert capsys.readouterr().out == ""
