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


def test_prune_twin(nb):
    """Instances hold an orphan only when no other ontology defines their label."""
    from tasks.components.ontology import prune

    render.__wrapped__(MockContext(), ontology="Metaontology")
    nb.run_query("""
        CREATE (keeper:OntologyMetadata {nid: 'prune-keeper', name: 'keeper'})
        CREATE (keeper)-[:DEFINES]->(:OntologyNode {nid: 'prune-owner', label: 'Twin'})
        CREATE (:OntologyNode {nid: 'prune-twin', label: 'Twin'})
        CREATE (:OntologyNode {nid: 'prune-lonely', label: 'Lonely'})
        CREATE (:Twin {nid: 'prune-twin-instance'})
        CREATE (:Lonely {nid: 'prune-lonely-instance'})
    """)

    prune.__wrapped__(MockContext(), confirm=True)

    remaining = {r["nid"] for r in nb.get_data(
        "MATCH (n) WHERE n.nid STARTS WITH 'prune-' RETURN n.nid AS nid"
    )}
    assert remaining == {"prune-keeper", "prune-owner", "prune-lonely",
                         "prune-twin-instance", "prune-lonely-instance"}


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


def test_delete(nb):
    """An ontology's metadata and the nodes it alone defines go; its dependency stays."""
    import pytest

    from tasks.components.ontology import delete

    render.__wrapped__(MockContext(), ontology="Ftir")
    ftir_nids = {r["nid"] for r in nb.get_data(
        "MATCH (:OntologyMetadata {name: 'Ftir'})-[:DEFINES]->(n) RETURN n.nid AS nid"
    )}
    assert ftir_nids

    # A dependency cannot go while its dependent stays behind to point at it.
    with pytest.raises(SystemExit):
        delete.__wrapped__(MockContext(), ontology="Spectroscopy", confirm=True)

    delete.__wrapped__(MockContext(), ontology="Ftir", confirm=True)

    names = {r["name"] for r in nb.get_data("MATCH (m:OntologyMetadata) RETURN m.name AS name")}
    assert "Ftir" not in names and "Spectroscopy" in names
    assert nb.get_data("MATCH (n) WHERE n.nid IN $nids RETURN count(n) AS c",
                       {"nids": list(ftir_nids)})[0]["c"] == 0


def test_delete_keeps_instances(nb):
    """A class still carrying instances outlives its ontology — it has no edge
       back to them, so only the label check can see they exist."""
    import subprocess

    from tasks.components.ontology import delete

    render.__wrapped__(MockContext(), ontology="Ftir")
    label = nb.get_data(
        "MATCH (:OntologyMetadata {name: 'Ftir'})-[:DEFINES]->(n:OntologyNode) "
        "RETURN n.label AS label ORDER BY label LIMIT 1"
    )[0]["label"]
    nid = subprocess.run(["uuidgen"], capture_output=True, text=True).stdout.strip()
    nb.run_query(f"CREATE (n:{label} {{nid: $nid}})", {"nid": nid})

    delete.__wrapped__(MockContext(), ontology="Ftir", confirm=True)

    assert nb.count(label=label) == 1                            # the instance survives
    kept = nb.get_data(
        """
        MATCH (n:OntologyNode {label: $label})
        WITH n, size([(n)<-[:DEFINES]-(m) | m]) AS defines
        RETURN count(n) AS nodes, sum(defines) AS claimed
        """,
        {"label": label},
    )[0]
    assert kept == {"nodes": 1, "claimed": 0}       # class node kept, now an orphan


def test_delete_twin(nb):
    """A class whose label another ontology still defines goes with its own —
       the instances stay defined by the twin, so they cannot hold it."""
    import subprocess

    from tasks.components.ontology import delete

    def uuid4():
        return subprocess.run(["uuidgen"], capture_output=True, text=True).stdout.strip()

    render.__wrapped__(MockContext(), ontology="Ftir")
    label = nb.get_data(
        "MATCH (:OntologyMetadata {name: 'Ftir'})-[:DEFINES]->(n:OntologyNode) "
        "RETURN n.label AS label ORDER BY label LIMIT 1"
    )[0]["label"]
    keeper, owner, instance = uuid4(), uuid4(), uuid4()
    nb.run_query(
        f"""
        CREATE (k:OntologyMetadata {{nid: $keeper, name: 'keeper'}})
        CREATE (k)-[:DEFINES]->(:OntologyNode {{nid: $owner, label: $label}})
        CREATE (:{label} {{nid: $instance}})
        """,
        {"keeper": keeper, "owner": owner, "instance": instance, "label": label},
    )

    delete.__wrapped__(MockContext(), ontology="Ftir", confirm=True)

    assert nb.count(label=label) == 1                            # the instance survives
    kept = {r["nid"] for r in nb.get_data(
        "MATCH (n:OntologyNode {label: $label}) RETURN n.nid AS nid", {"label": label})}
    assert kept == {owner}                            # Ftir's twin went, the owner stayed


def test_doomed_set(nb):
    """--closure keeps every dependency something outside the set still needs."""
    import subprocess

    from tasks.components.ontology import _doomed_set

    def uuid4():
        return subprocess.run(["uuidgen"], capture_output=True, text=True).stdout.strip()

    root, mid, shared, base, keeper = (uuid4() for _ in range(5))
    nb.run_query(
        """
        UNWIND $meta AS m CREATE (:OntologyMetadata {nid: m.nid, name: m.name})
        WITH 1 AS _
        UNWIND $deps AS d
        MATCH (a:OntologyMetadata {nid: d[0]}), (b:OntologyMetadata {nid: d[1]})
        CREATE (a)-[:DEPENDS_ON]->(b)
        """,
        {"meta": [{"nid": n, "name": s} for n, s in
                  ((root, "root"), (mid, "mid"), (shared, "shared"),
                   (base, "base"), (keeper, "keeper"))],
         "deps": [[root, mid], [mid, shared], [shared, base], [keeper, shared]]},
    )

    assert _doomed_set(nb, root, closure=False) == [root]
    # `shared` is rescued by `keeper`, and `base` transitively with it.
    assert _doomed_set(nb, root, closure=True) == sorted([root, mid])
