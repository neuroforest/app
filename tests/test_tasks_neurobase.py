"""Integration tests for `nde neurobase.validate`.

Uses the Test ontology (assets/test/input/ontology/test.nfx) and the
test_pass / test_fail knowledge fixtures (assets/test/input/knowledge/).
"""
import pytest
from invoke import MockContext

from neuro.utils.internal_utils import get_path
from tasks.components import neurobase
from tasks.components.ontology import render

KNOWLEDGE = get_path("assets") / "test" / "input" / "knowledge"


@pytest.fixture
def test_ontology(nb):
    render.__wrapped__(MockContext(), ontology="Test")
    return nb


def _load(nb, filename):
    nb.nodes.import_nfx(KNOWLEDGE / filename, validate=False)


def test_has_key(test_ontology):
    found = neurobase._unique_property_labels(test_ontology, "TestKey")
    assert {(p["property"], p["via"]) for p in found} == {("id", "HAS_KEY")}


def test_unique_property(test_ontology):
    found = neurobase._unique_property_labels(test_ontology, "TestUnique")
    assert {(p["property"], p["via"]) for p in found} == {("code", "UNIQUE_PROPERTY")}


def test_no_unique(test_ontology):
    assert neurobase._unique_property_labels(test_ontology, "TestRequire") == []


def test_duplicates(test_ontology):
    _load(test_ontology, "test_fail.nfx")
    dups = neurobase._find_duplicate_values(test_ontology, "TestKey", "id")
    assert len(dups) == 1
    assert dups[0]["value"] == "DUP"
    assert dups[0]["count"] == 2


def test_no_duplicates(test_ontology):
    _load(test_ontology, "test_pass.nfx")
    assert neurobase._find_duplicate_values(test_ontology, "TestKey", "id") == []
    assert neurobase._find_duplicate_values(test_ontology, "TestUnique", "code") == []


def test_pass(test_ontology):
    _load(test_ontology, "test_pass.nfx")
    neurobase.validate.__wrapped__(MockContext(), fmt="json")


def test_fail(test_ontology):
    _load(test_ontology, "test_fail.nfx")
    with pytest.raises(SystemExit) as exc:
        neurobase.validate.__wrapped__(MockContext(), fmt="json")
    assert exc.value.code == 1


def test_report(test_ontology, capsys):
    _load(test_ontology, "test_fail.nfx")
    with pytest.raises(SystemExit):
        neurobase.validate.__wrapped__(MockContext(), fmt="json")
    out = capsys.readouterr().out

    import json
    report = json.loads(out)
    by_label = {e["label"]: e for e in report}

    key_unique = by_label["TestKey"]["unique"]
    assert len(key_unique) == 1
    assert key_unique[0]["property"] == "id"
    assert key_unique[0]["via"] == "HAS_KEY"
    assert len(key_unique[0]["duplicates"]) == 1
    assert key_unique[0]["duplicates"][0]["value"] == "DUP"
    assert by_label["TestKey"]["unique_fail"] == 1

    code_unique = by_label["TestUnique"]["unique"]
    assert code_unique[0]["via"] == "UNIQUE_PROPERTY"
    assert by_label["TestUnique"]["unique_fail"] == 1

    assert by_label["TestRequire"]["unique"] == []
    assert by_label["TestRequire"]["unique_fail"] == 0


def test_required_relationship(test_ontology, capsys):
    _load(test_ontology, "test_fail.nfx")
    with pytest.raises(SystemExit):
        neurobase.validate.__wrapped__(MockContext(), fmt="json")
    out = capsys.readouterr().out

    import json
    report = json.loads(out)
    by_label = {e["label"]: e for e in report}

    rrr = by_label["TestRequireRel"]
    assert rrr["count"] == 1
    assert rrr["fail"] == 1
    assert [d["missing_rel"] for d in rrr["details"]] == [["POINTS_TO"]]
