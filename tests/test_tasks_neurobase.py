"""Integration tests for `nde neurobase.validate`.

Uses the Test ontology (assets/test/input/ontology/test.nfx) and per-concern
knowledge fixtures under assets/test/input/knowledge/ — one shared `test-pass.nfx`
plus `<concern>-fail.nfx` files that isolate a single violation kind.
"""
import json

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


def _validate_report(nb, fixture):
    _load(nb, fixture)
    with pytest.raises(SystemExit) as exc:
        neurobase.validate.__wrapped__(MockContext(), fmt="json")
    assert exc.value.code == 1


def test_has_key(test_ontology):
    found = neurobase._unique_property_labels(test_ontology, "TestKey")
    assert {(p["property"], p["via"]) for p in found} == {("id", "HAS_KEY")}


def test_unique_property(test_ontology):
    found = neurobase._unique_property_labels(test_ontology, "TestUnique")
    assert {(p["property"], p["via"]) for p in found} == {("code", "UNIQUE_PROPERTY")}


def test_no_unique(test_ontology):
    assert neurobase._unique_property_labels(test_ontology, "TestRequire") == []


def test_duplicates(test_ontology):
    _load(test_ontology, "unique-fail.nfx")
    dups = neurobase._find_duplicate_values(test_ontology, "TestKey", "id")
    assert len(dups) == 1
    assert dups[0]["value"] == "DUP"
    assert dups[0]["count"] == 2


def test_no_duplicates(test_ontology):
    _load(test_ontology, "test-pass.nfx")
    assert neurobase._find_duplicate_values(test_ontology, "TestKey", "id") == []
    assert neurobase._find_duplicate_values(test_ontology, "TestUnique", "code") == []


def test_pass(test_ontology):
    _load(test_ontology, "test-pass.nfx")
    neurobase.validate.__wrapped__(MockContext(), fmt="json")


def test_unique_violation(test_ontology, capsys):
    _validate_report(test_ontology, "unique-fail.nfx")
    by_label = {e["label"]: e for e in json.loads(capsys.readouterr().out)}

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


def test_required_property_violation(test_ontology, capsys):
    _validate_report(test_ontology, "required-property-fail.nfx")
    by_label = {e["label"]: e for e in json.loads(capsys.readouterr().out)}

    entry = by_label["TestRequire"]
    assert entry["count"] == 1
    assert entry["fail"] == 1
    assert [d["missing"] for d in entry["details"]] == [["name"]]


def test_required_relationship_violation(test_ontology, capsys):
    _validate_report(test_ontology, "required-relationship-fail.nfx")
    by_label = {e["label"]: e for e in json.loads(capsys.readouterr().out)}

    entry = by_label["TestRequireRel"]
    assert entry["count"] == 1
    assert entry["fail"] == 1
    assert [d["missing_rel"] for d in entry["details"]] == [["POINTS_TO"]]
