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
