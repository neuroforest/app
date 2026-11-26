"""Integration tests for `invoke neurobase.validate`.

Uses the Test ontology (tests/.nf/ontology/test.nfx) and per-concern knowledge
fixtures under tests/.nf/knowledge/ - one shared `test-pass.nfx` plus
`<concern>-fail.nfx` files that isolate a single violation kind. `tests/.nf` is
the suite's own consolidated root (token `test`), listed in the testing
environment's `PLUGINS`.
"""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from invoke import MockContext

from neuro.base import NeuroBase
from neuro.core.deep.object import Object
from neuro.utils.internal_utils import get_path
from tasks.components import neurobase
from tasks.components.ontology import render

KNOWLEDGE = get_path("app") / "tests" / ".nf" / "knowledge"


@pytest.fixture
def test_ontology(nb):
    render.__wrapped__(MockContext(), ontology="Test")
    return nb


@pytest.fixture
def test_ontology_child(nb):
    """Test plus its dependant TestChild, so ChildAlpha (SUBCLASS_OF TestRequire)
    is present for the antichain check."""
    render.__wrapped__(MockContext(), ontology="Test", dependants=True)
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


def test_multilabel_pass(test_ontology):
    _load(test_ontology, "multilabel-pass.nfx")
    # A node labelled [TestRequire, TestKey] validates against the union of both
    # - no SystemExit. Per-label validation would fail it (each label sees the
    # other's property as undefined).
    neurobase.validate.__wrapped__(MockContext(), fmt="json")


def test_multilabel_required_union(test_ontology, capsys):
    _validate_report(test_ontology, "multilabel-required-fail.nfx")
    by_label = {e["label"]: e for e in json.loads(capsys.readouterr().out)}
    for label in ("TestRequire", "TestKey"):
        entry = by_label[label]
        assert entry["fail"] == 1
        assert [d["missing"] for d in entry["details"]] == [["name"]]


def test_multilabel_conflict(test_ontology, capsys):
    _validate_report(test_ontology, "multilabel-conflict-fail.nfx")
    by_label = {e["label"]: e for e in json.loads(capsys.readouterr().out)}
    # name is String on TestRequire and Color on TestColorName - "hello" can
    # satisfy neither pair, so the value is invalid and both declarations named.
    for label in ("TestRequire", "TestColorName"):
        entry = by_label[label]
        assert entry["fail"] == 1
        invalid = entry["details"][0]["invalid"]
        assert invalid and invalid[0][0] == "name"
        reason = invalid[0][1]
        assert "String (TestRequire)" in reason and "Color (TestColorName)" in reason


def test_multilabel_redundant_label(test_ontology_child, capsys):
    _validate_report(test_ontology_child, "redundant-label-fail.nfx")
    by_label = {e["label"]: e for e in json.loads(capsys.readouterr().out)}
    entry = by_label["ChildAlpha"]
    assert entry["fail"] == 1
    assert entry["details"][0]["redundant"] == [["ChildAlpha", "TestRequire"]]


def test_multilabel_write_path_accepts_union(test_ontology):
    # The write path (objects.put → ObjectValidator) validates against the union
    # of the node's labels, so a two-label node writes without a violation.
    obj = Object(
        labels=["TestRequire", "TestKey"],
        properties={"nid": "2d17c771-dd3f-48fb-bd0e-225bf7ab059f", "name": "w", "id": "WK1"},
    )
    test_ontology.objects.put(obj, identifier_key="nid")


def test_multilabel_write_path_rejects_redundant(test_ontology_child):
    obj = Object(
        labels=["ChildAlpha", "TestRequire"],
        properties={"nid": "167b753f-0261-4614-a7e7-8d4a44db0239", "name": "w", "shade": "navy"},
    )
    with pytest.raises(ValueError) as exc:
        test_ontology_child.objects.put(obj, identifier_key="nid")
    assert "redundant label" in str(exc.value)


def test_run_tests(nb):
    """A `-fail` fixture's value violations are expected, a clean one has none,
    and neither fails on form or pins."""
    from neuro.base import plugins
    from tasks.components import nfx as nfx_tasks

    paths = [KNOWLEDGE / "test-pass.nfx", KNOWLEDGE / "required-property-fail.nfx"]
    by_name = {r["name"]: r for r in nfx_tasks.run_tests(nb, plugins.effective_roots(), paths)}

    assert by_name["TestPass"]["failures"] == [] and "expected" not in by_name["TestPass"]
    failing = by_name["TestRequiredPropertyFail"]
    assert failing["failures"] == [] and failing["outcome"] == "passed"
    assert len(failing["expected"]) == 1 and "missing" in failing["expected"][0]


def test_run_tests_knowledge_chain(nb):
    """A knowledge module that pins knowledge only: its classes come from the
    ontology behind the pin, its edge lands on a node the pinned module declares,
    and a pin-only module loads the whole chain."""
    from neuro.base import plugins
    from tasks.components import nfx as nfx_tasks

    paths = [KNOWLEDGE / f"kk-{x}.nfx" for x in "abc"]
    records = nfx_tasks.run_tests(nb, plugins.effective_roots(), paths)

    assert {r["name"]: r["failures"] for r in records} == {"kk-a": [], "kk-b": [], "kk-c": []}
    # one import pass: the chain extends what is loaded, the target is judged from its file
    loaded = {r["name"] for r in nb.get_data("MATCH (m:KnowledgeMetadata) RETURN m.name AS name")}
    assert loaded == {"kk-a", "kk-b"}


def test_import_document(nb):
    """Loaded through its closure, each node stays with the module that declares it."""
    from neuro.base import nfx_load, plugins
    from neuro.base.index import NfxIndex

    idx = NfxIndex(*plugins.effective_roots())
    for _ in range(2):  # a second pass changes nothing
        for path in idx.closure(KNOWLEDGE / "kk-c.nfx", include_self=True):
            nfx_load.import_document(nb, idx, path)

    owners = nb.get_data("""
        MATCH (m:KnowledgeMetadata)-[:DEFINES]->(n)
        RETURN m.name AS module, count(n) AS nodes ORDER BY module
    """)
    assert [(r["module"], r["nodes"]) for r in owners] == [("kk-a", 2), ("kk-b", 1)]
    edges = nb.get_data("""
        MATCH (:KnowledgeMetadata {name: "kk-b"})-[:DEFINES]->(a)-[:POINTS_TO]->(b)
              <-[:DEFINES]-(owner:KnowledgeMetadata)
        RETURN owner.name AS owner
    """)
    assert [r["owner"] for r in edges] == ["kk-a"]
    pins = nb.get_data("""
        MATCH (m:KnowledgeMetadata)-[:DEPENDS_ON]->(d)
        RETURN m.name AS module, d.name AS dep ORDER BY module
    """)
    assert [(r["module"], r["dep"]) for r in pins] == [("kk-a", "Test"), ("kk-b", "kk-a"), ("kk-c", "kk-b")]


def test_print_info(nb, capsys):
    """Each kind lists its own modules; a dependency is named whatever its kind,
    and a knowledge tree runs down into the ontology behind it."""
    from neuro.base import nfx_load, plugins
    from neuro.base.index import NfxIndex
    from tasks.components import nfx as nfx_tasks

    idx = NfxIndex(*plugins.effective_roots())
    for path in idx.closure(KNOWLEDGE / "kk-c.nfx", include_self=True):
        nfx_load.import_document(nb, idx, path)

    assert {r["name"] for r in nfx_tasks.loaded_modules(nb, "knowledge")} == {"kk-a", "kk-b", "kk-c"}
    kinds = {r["name"]: r["type"] for r in nfx_tasks.loaded_modules(nb)}
    assert kinds["kk-a"] == "knowledge" and kinds["Test"] == "ontology"

    nfx_tasks.print_info(nb, kind="knowledge")
    table = capsys.readouterr().out
    assert "3 knowledge modules, 3 nodes" in table and "Type" not in table.splitlines()[0]

    nfx_tasks.print_info(nb, kind="knowledge", tree=True)
    tree = capsys.readouterr().out.splitlines()
    assert tree[0].startswith("kk-c@") and tree[1].startswith("└── kk-b@")
    assert any("kk-a@" in line for line in tree[2:]) and any("Test@" in line for line in tree[3:])

    nfx_tasks.print_info(nb)
    assert "Type" in capsys.readouterr().out.splitlines()[0]

    with pytest.raises(SystemExit):
        nfx_tasks.print_info(nb, kind="bogus")


def test_import_dependencies(nb):
    """`knowledge.import`'s path: a pinned knowledge module that is missing is
    loaded with the ontologies behind it, one already there is reused."""
    from neuro.base import nfx, plugins
    from neuro.base.index import NfxIndex

    idx = NfxIndex(*plugins.effective_roots())
    doc = nfx.read(KNOWLEDGE / "kk-c.nfx")
    seen = []
    for _ in range(2):
        nb.metaontology._import_dependencies(
            doc.dependencies, index=idx,
            on_import=lambda name, imported, depth: seen.append((name, imported)),
        )

    assert ("test-kk-b", True) in seen and ("test-kk-a", True) in seen
    assert ("test-kk-b", False) in seen and ("test-kk-a", False) in seen
    assert nb.get_data("MATCH (:TestRequireRel)-[r:POINTS_TO]->(:TestKey) RETURN count(r) AS n")[0]["n"] == 1


def test_start():
    neurobase.start(MockContext())
    with NeuroBase() as nb:
        assert nb.get_data("RETURN 1 AS ok")[0]["ok"] == 1


def test_backup_lock_path(tmp_path, monkeypatch):
    """One lock per container, whatever the archive path."""
    import tempfile

    monkeypatch.setenv("BASE_NAME", "some-base")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("ARCHIVE", str(tmp_path / "one"))
    path = neurobase._backup_lock_path()
    assert path == tmp_path / "neurobase-some-base.lock"
    monkeypatch.setenv("ARCHIVE", str(tmp_path / "two"))
    assert neurobase._backup_lock_path() == path

    monkeypatch.setenv("BASE_NAME", "other-base")
    assert neurobase._backup_lock_path() != path

    monkeypatch.delenv("XDG_RUNTIME_DIR")
    fallback = neurobase._backup_lock_path()
    assert fallback.parent == Path(tempfile.gettempdir())
    assert fallback.name == f"neurobase-{os.getuid()}-other-base.lock"


def _backup_dirs(archive):
    base = os.environ["BASE_NAME"]
    return sorted(p for p in (archive / "base").iterdir() if p.name.startswith(f"{base}-"))


def test_backup_data_only_then_full(tmp_path, monkeypatch):
    """`neurobase.backup` dumps the data volume alone by default and the whole
    container with --full; every file is ours and 0600. The base
    is stopped by the dump and started again at the end."""
    monkeypatch.setenv("ARCHIVE", str(tmp_path))
    neurobase.start(MockContext())

    neurobase.backup(MockContext())
    dumps = _backup_dirs(tmp_path)
    assert len(dumps) == 1
    assert sorted(p.name for p in dumps[0].iterdir()) == ["data.tar.gz"]

    # MOMENT_4 is fixed at import, so a second dump in this process needs its own name
    dumps[0].rename(dumps[0].with_name(dumps[0].name + "-first"))

    neurobase.backup(MockContext(), full=True)
    dumps = [d for d in _backup_dirs(tmp_path) if not d.name.endswith("-first")]
    assert len(dumps) == 1
    names = sorted(p.name for p in dumps[0].iterdir())
    assert names == ["container.tar", "data.tar.gz", "logs.tar.gz"]
    for p in dumps[0].iterdir():
        st = p.stat()
        assert st.st_uid == os.getuid(), p
        assert stat.S_IMODE(st.st_mode) == 0o600, p
        assert st.st_size > 0, p

    # A cold start of the test container re-fetches its plugins and can take longer
    # than the 32 s `start` allows: bring it up and wait generously, then `start`
    # finds it running.
    subprocess.run(["docker", "start", os.environ["BASE_NAME"]], check=True, capture_output=True)
    neurobase.verify_neo4j(timeout=300)
    neurobase.start(MockContext())
    with NeuroBase() as nb:
        assert nb.get_data("RETURN 1 AS ok")[0]["ok"] == 1
