import contextlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path

import invoke

from neuro.base import NeuroBase, nf_repo, nfx, nfx_load, plugins, schema
from neuro.base.index import KnowledgeIndex, NfxIndex, OntologyIndex
from neuro.base.labels import LabelExpansionError
from neuro.base.metaontology import OntologyViolations
from neuro.base.ontology import ObjectValidator, Ontology
from neuro.utils import exceptions, terminal_components, terminal_style

from tasks.actions import setup
from tasks.components import neurobase, nf_common


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
    for label, holders in report.get("orphaned", ()):
        status.log(f"  {terminal_style.WARN} {label} no longer declared, "
                   f"kept: {holders} edge(s), instance(s) or undeclared label(s) and "
                   f"property(ies) still on it")
    for label in report.get("removed", ()):
        status.log(f"  − {label} removed, nothing was left on it")
    if report.get("edges_pruned"):
        status.log(f"  − {report['edges_pruned']} edge(s) pruned")


# The one place that says which nodes belong to the ontology layer, shared so
# `print_orphan_hint` and `ontology.prune` can never disagree about what an
# orphan is - they did once, and the hint that tells you to run `prune` was
# blind to exactly the nodes `prune` was.
#
# Every kind the layer stores is an `OntologyObject`: classes are
# `OntologyNode`, relationship types are `OntologyRelationship`, and a property
# is labelled by its *type* - `Uuid`, `String`, `DateTime`, … - which is why an
# enumeration of the first two silently skipped a whole third of the layer.
# Ask the metaontology for the subtree rather than restating it (`:Label+`,
# `neuro.base.labels`), so a new property type is covered the day it is
# declared. Leaves `orphans` (a list of nodes) in scope.
_ORPHAN_SCOPE = """
    MATCH (n:OntologyObject+)
    WHERE NOT (n)<-[:DEFINES]-(:OntologyMetadata)
    WITH collect(n) AS orphans
"""

# Carries the nodes forward rather than re-matching them by nid: an unlabelled
# `MATCH (n {nid: ...})` is a full scan of the base, and once per orphan it cost
# 20s on a large base where the label-scoped pass costs one.
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
    WHERE NOT (o:Metadata+)
      AND NOT (o)<-[:DEFINES]-(:OntologyMetadata)
      AND NOT o IN orphans
    RETURN n.nid AS nid, coalesce(n.label, n.nid) AS label,
           labels(n)[0] AS kind,
           count(r) AS held, collect(DISTINCT type(r))[0..4] AS rel_types
    ORDER BY label
"""


# An instance carries its class as a *label* and holds no relationship back to
# the class node, so the edge test above cannot see it: by that measure a class
# with ten thousand instances looks exactly as isolated as one with none. A
# class still carrying instances has to outlive its ontology - delete it and
# those instances are labelled by a class nothing defines, which is the drift
# `neurobase.validate` reports as an undefined node type.
_INSTANCE_COUNTS = """
    MATCH (i)
    WHERE any(l IN labels(i) WHERE l IN $labels)
      AND NOT i:OntologyMetadata
      AND NOT (i)<-[:DEFINES]-(:OntologyMetadata)
    RETURN [l IN labels(i) WHERE l IN $labels][0] AS label, count(*) AS instances
"""


def instance_counts(nb, labels):
    """`label` → live instances, for the class labels given.

    One scan for the whole set, never one per class: the match is unlabelled by
    necessity (the question *is* which labels are in use), so it is the most
    expensive thing either caller does. An empty label set short-circuits.
    """
    labels = sorted({label for label in labels if label})
    if not labels:
        return {}
    return {r["label"]: r["instances"]
            for r in nb.get_data(_INSTANCE_COUNTS, {"labels": labels})}


# Two ontologies may declare the same class label under different nids - two may
# both declare `Project`. Nothing on an instance says which
# node it means, so the label count above is attributed to both. But the reason
# instances hold a class is that deleting it leaves them labelled by a class
# nothing defines, and while another ontology still defines the label that
# cannot happen. Counting them anyway made a withdrawn twin undeletable for
# good: nothing would ever take the other's instances away from it.
_TWINS = """
    MATCH (keeper:OntologyMetadata)-[:DEFINES]->(n:OntologyNode)
    WHERE n.label IN $labels AND NOT keeper.nid IN $exclude
    RETURN n.label AS label, collect(DISTINCT keeper.name) AS keepers
"""


def attach_usage(nb, rows, exclude=()):
    """Stamp `instances` and `twin` on each row.

    `twin` names the ontologies outside `exclude` that still define the row's
    label; it is only asked for labels with instances, the one case it decides.
    `exclude` is the set being withdrawn - a twin inside it goes too.
    """
    counts = instance_counts(nb, [r["label"] for r in rows])
    labels = sorted({r["label"] for r in rows if counts.get(r["label"])})
    twins = {r["label"]: r["keepers"] for r in nb.get_data(
        _TWINS, {"labels": labels, "exclude": list(exclude)})} if labels else {}
    for r in rows:
        r["instances"] = counts.get(r["label"], 0)
        r["twin"] = twins.get(r["label"], [])


def is_held(row):
    """Whether the wider graph still needs this node: an edge from outside the
    ontology layer, or instances no surviving twin will go on defining."""
    return bool(row["held"] or (row["instances"] and not row["twin"]))


def orphan_nodes(nb, with_edges=False):
    """Every ontology-layer node no `OntologyMetadata` defines any more.

    `with_edges` adds `held` / `rel_types` / `instances` / `twin` - how much of
    the wider graph still reaches the orphan, which is what decides whether it is
    safe to delete. The hint does not need it and does not pay for it.
    """
    rows = nb.get_data(_ORPHANS_WITH_EDGES if with_edges else _ORPHANS)
    if with_edges:
        attach_usage(nb, rows)
    return rows


def print_orphan_hint(nb):
    """Print the review commands when the graph holds undefined ontology nodes.

    `import_nfx` releases a node it stops declaring rather than deleting it
    and logs each one per-file. In a root import those lines
    scroll past inside a long dependency tree, so the run ends with no sign
    that the graph now holds nodes no `.nfx` declares - real drift, invisible.

    Asked of the graph rather than accumulated from the reports: `import_nfx`
    returns a report only for its own file, and surfaces a nested dependency
    import as a name through `on_import`. Reading the returned report would
    therefore miss exactly the common case - a root import whose orphans come
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
    """Print the re-import commands for the modules that depend on anything
    written this run and were not themselves written. `idx` decides which
    kinds are looked at: over an `NfxIndex` a knowledge module pinning a
    re-imported ontology is named too, by the qualified name that always
    resolves back to it.

    Detect and print only - never re-import them here. Re-importing in the same
    run would let a command aimed at one module write to modules the user
    never named.

    "Not written" is decided by nid, not by which file the operator named: a
    root import writes its whole closure, and a dependency it just imported
    fresh is as written as the target. Excluding only the named path made the
    hint list ontologies the same run had written - a checklist that never
    converged, since each named ontology then pointed back at the other.
    """
    pending = []
    for path in idx.all_targets():
        doc = nfx.read(path)
        if doc.nid in written_nids:
            continue
        if written_nids & set(doc.dep_nids):
            pending.append(idx.qualified_for(doc.nid) or doc.name or path.stem)
    if not pending:
        return
    print(f"\n{terminal_style.WARN} Dependents not re-imported:")
    for name in sorted(pending):
        print(f"    nfx.import {name}")


def run_import_task(target, kind=""):
    """The body of `nfx.import`, callable from the per-kind shortcuts.

    One module, named by stem, name, qualified name, nid or path, is written
    with the dependencies the base lacks - whatever their kinds. `kind` only
    narrows what the name may resolve to: a shortcut refuses a module of the
    other kind rather than import it under the wrong verb.
    """
    if kind not in _KIND_VIEWS:
        print(f"{terminal_style.FAIL} --kind is `ontology` or `knowledge`, not {kind!r}")
        raise SystemExit(1)
    view, noun = _KIND_VIEWS[kind]
    if not target:
        print(f"{terminal_style.FAIL} a target is required: the module to import")
        raise SystemExit(1)
    trees = plugins.effective_trees()
    idx = NfxIndex(*trees)  # every kind: a module pins, and is pinned by, either

    # Among the asked kind when it has a module of that name, so a name both
    # kinds use means that kind's; otherwise among all, to say what it is.
    narrowed = view(*trees)
    path = nf_common.resolve(narrowed if narrowed.matches(target) else idx, target)
    if not path:
        print(f"{terminal_style.FAIL} {noun} not found: {target}")
        raise SystemExit(1)
    doc = nfx.read(path)
    if doc.is_namespace:
        print(f"{terminal_style.FAIL} {path} is a namespace declaration, not a module - nothing to "
              f"import (its graph form is the `:NfxPackage`, seeded by its own importer)")
        raise SystemExit(1)
    if kind and ("knowledge" if doc.type == "knowledge" else "ontology") != kind:
        print(f"{terminal_style.FAIL} {doc.name or target} is {doc.type or 'an ontology'}, not {kind} "
              f"- `nfx.import {target}` imports either kind")
        raise SystemExit(1)

    written = {doc.nid}
    with NeuroBase() as nb:
        with terminal_components.step(doc.name or path.stem) as status:
            log_dep = make_dep_logger(status)

            def on_import(dep_name, imported, depth=1):
                if imported:
                    dep_path = idx.resolve(dep_name)
                    if dep_path:
                        written.add(nfx.read(dep_path).nid)
                log_dep(dep_name, imported, depth)

            report = nb.metaontology.import_nfx(path, index=idx, on_import=on_import)
            print_import_report(status, report)
        print_orphan_hint(nb)
    print_dependant_hint(idx, written - {None, ""})


def resolve_target(idx, name, kind="Target"):
    """Resolve a single nfx target by name/nid, or return all targets if name is empty."""
    if name:
        path = nf_common.resolve(idx, name)
        if not path:
            print(f"{terminal_style.FAIL} {kind} not found: {name}")
            raise SystemExit(1)
        return [path]
    return idx.all_targets()


def load_closure(nb, idx, path, loaded, include_self=True):
    """Load the dependency closure of `path` into `nb`, one status line per
    document, skipping what `loaded` (a set of paths, updated here) already
    holds. `idx` is an `NfxIndex`: the closure is type-blind."""
    for dep_path in idx.closure(path, include_self=include_self):
        if dep_path in loaded:
            continue
        with terminal_components.step(nfx.read(dep_path).name or dep_path.stem):
            nfx_load.import_document(nb, idx, dep_path)
        loaded.add(dep_path)


def validate_knowledge(nb, path):
    """Validate knowledge (instance) nodes in an NFX file against the loaded
    ontology, appending per-node violations onto `nb.metaontology.violations`
    so the caller's gating and printing pick them up uniformly. Nodes whose
    labels don't resolve to any known ontology-object subclass are classified
    via `schema.TypeRegistry` and aggregated as undefined property /
    relationship / node types - typo'd type labels fail loudly."""

    class _Node:
        def __init__(self, labels, properties):
            self.labels = labels
            self.properties = properties

    doc = nfx.read(path)
    registry = schema.TypeRegistry(nb)
    # `registry.known` holds the ontology layer's own kinds (subclasses of
    # OntologyNode, …), which no instance carries: an instance is labelled by a
    # *class*, and a class is an `:OntologyNode` whatever it descends from.
    # Without this every instance read as an undefined node type and was
    # skipped before its values were looked at.
    classes = {r["label"] for r in nb.get_data("MATCH (n:OntologyNode) RETURN n.label AS label")}

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

        kind = None
        if not any(label in classes for label in labels):
            kind = registry.classify_undefined(labels, edge_map.get(entry["nid"], set()))
        if kind is not None:
            type_label = labels[0] if labels else "?"
            undefined[kind].setdefault(type_label, identifier)
            continue

        node_props = {"nid": entry["nid"], **entry_props}
        violations = ObjectValidator(nb, _Node(labels, node_props)).get_violations()
        if violations:
            nb.metaontology.violations.violations.append(
                (identifier, ":".join(labels), violations)
            )

    nb.metaontology.violations.undefined_property_types.extend(sorted(undefined["property"].items()))
    nb.metaontology.violations.undefined_relationship_types.extend(sorted(undefined["relationship"].items()))
    nb.metaontology.violations.undefined_node_types.extend(sorted(undefined["node"].items()))


def _run_module_tests(path, trees):
    """A module's pytest file, run; the output when it fails, else None."""
    test_path = nf_repo.module_test_path(path, trees)
    if test_path is None:
        return None
    pytest_bin = os.path.join(setup.get_nenv_dir(), "bin", "pytest")
    result = subprocess.run([pytest_bin, "--import-mode=importlib", str(test_path)],
                            capture_output=True, text=True)
    if result.returncode == 0:
        return None
    return (result.stdout + result.stderr).rstrip() or f"pytest failed (exit {result.returncode})"


def _expects_violations(record):
    """A knowledge document named `<concern>-fail.nfx` is a fixture of invalid
    instances: its value violations are what it is for, asserted by the suite
    that loads it. Its form and its pins are judged like any document's."""
    return record["type"] == "knowledge" and Path(record["path"]).stem.endswith("-fail")


def run_tests(nb, trees, targets=None):
    """Test `.nfx` documents, each by its type; one record per document.

    - ontology / metaontology: imported with its closure, the schema judged
      (`is_ontology_valid`), its pins checked, its pytest file run;
    - knowledge: its closure loaded - the ontologies and the knowledge modules
      it pins, and theirs - every node's values judged against it, its pins
      checked, its pytest file run; a `<concern>-fail.nfx` fixture keeps its
      value violations under `expected`, not `failures`;
    - namespace: the declaration's own form and pins - it has no schema.

    What is loaded for a document does not depend on its type, only how it is
    judged does: the closure is `NfxIndex.closure`, the same walk the
    redundant-pin check makes. A knowledge module in a closure is
    loaded, not judged - its own record judges it.

    `targets` are paths (default: every document of `trees`, declarations
    included). The base is cleared only when it holds something outside the
    next document's closure, and documents that extend what is loaded go
    first - a chain of dependants is one import pass, not one per document.
    A document that fails on its own terms (`document_failures`) is not
    imported. `nb` is a base this may wipe: the TESTING one.
    """
    trees = [Path(r).resolve() for r in trees]
    idx = NfxIndex(*trees)
    if targets is None:
        targets = [ns.path for ns in idx.namespaces()] + idx.all_targets()

    records = {}
    closure = {}
    for path in dict.fromkeys(Path(t).resolve() for t in targets):
        doc = nfx.read(path)
        record = {"name": doc.name or path.stem, "type": doc.type, "path": str(path),
                  "started": time.monotonic(), "failures": [], "warnings": []}
        records[path] = record
        if doc.is_namespace:
            record["failures"] = nf_repo.namespace_failures(idx, path)
        else:
            record["failures"] = nf_repo.document_failures(idx, path)
            if not record["failures"]:
                # A knowledge document is judged from the file and never loaded
                # itself; an ontology is judged in the base, so it is.
                try:
                    closure[path] = [Path(p).resolve() for p in
                                     idx.closure(path, include_self=doc.type != "knowledge")]
                except exceptions.NfxViolation as e:
                    record["failures"] = [str(e)]
        record["duration_s"] = time.monotonic() - record.pop("started")

    loaded: set[Path] = set()
    remaining = list(closure)
    while remaining:
        path = next((p for p in remaining if loaded <= set(closure[p])), remaining[0])
        remaining.remove(path)
        record = records[path]
        started = time.monotonic()
        if not loaded <= set(closure[path]):
            nb.clear(confirm=True)
            loaded = set()
        try:
            for dep in closure[path]:
                if dep not in loaded:
                    nfx_load.import_document(nb, idx, dep)
                    loaded.add(dep)
        except (exceptions.NfxViolation, ValueError) as e:
            # The base now holds part of a closure: nothing may build on it.
            record["failures"].append(f"{dep.stem} failed to load: {e}")
            record["duration_s"] += time.monotonic() - started
            nb.clear(confirm=True)
            loaded = set()
            continue
        if record["type"] == "knowledge":
            nb.metaontology.violations = OntologyViolations()
            validate_knowledge(nb, path)
        else:
            nb.metaontology.is_ontology_valid()
        violations = [str(v) for v in nb.metaontology.violations]
        if _expects_violations(record):
            record["expected"] = violations
        else:
            record["failures"] += violations
        record["warnings"] = [str(w) for w in nb.metaontology.violations.warnings]
        record["failures"] += [str(e) for e in idx.check_dependency_versions(path)]
        output = _run_module_tests(path, trees)
        if output:
            record["failures"].append(output)
        record["duration_s"] += time.monotonic() - started

    for record in records.values():
        record["outcome"] = "failed" if record["failures"] else "passed"
        record["duration_s"] = round(record["duration_s"], 3)
        record["failure_count"] = len(record["failures"])
    return list(records.values())


def report_tests(records, fmt="text"):
    """Print the records of `run_tests`; exit 1 when any document failed."""
    if fmt == "json":
        print(json.dumps(records, indent=2, default=str))
    else:
        for record in records:
            mark = terminal_style.FAIL if record["failures"] else terminal_style.SUCCESS
            print(f"{mark} {record['name']}")
            for entry in record["failures"]:
                for line in entry.splitlines():
                    print(f"  {line}")
            for w in record["warnings"]:
                print(f"  {w}")
            if record.get("expected"):
                print(f"  {len(record['expected'])} violation(s), as the fixture intends")
    if any(r["failures"] for r in records):
        raise SystemExit(1)


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


def _test_targets(idx, target, noun="Nfx"):
    """Paths for a comma-separated `-t`: each a document by stem, name, nid or
    path; `namespace` names every root's declaration."""
    paths = []
    for key in (k.strip() for k in target.split(",")):
        if not key:
            continue
        if key.lower() == "namespace":
            paths += [ns.path for ns in idx.namespaces()]
            continue
        path = nf_common.resolve(idx, Path(key).stem if key.endswith(".nfx") and not Path(key).exists() else key)
        if not path:
            print(f"{terminal_style.FAIL} {noun} not found: {key}")
            raise SystemExit(1)
        paths.append(path)
    return paths


# `ontology.test` and `knowledge.test` are shortcuts for `nfx.test --kind …`
# the view a kind is resolved in, and what a miss is called.
_KIND_VIEWS = {
    "": (NfxIndex, "Nfx"),
    "ontology": (OntologyIndex, "Ontology"),
    "knowledge": (KnowledgeIndex, "Knowledge"),
}


def run_test_task(c, target="", trees="", fmt="text", out="", closure=False, kind=""):
    """The body of `nfx.test`, callable from the per-kind shortcuts.

    `kind` narrows what a name may resolve to and, with no target, what
    "everything" means; it never changes how a document is loaded or judged.
    `closure` adds each target's dependencies, of every type, as documents to
    test in their own right - without it they are loaded only.
    """
    if kind not in _KIND_VIEWS:
        print(f"{terminal_style.FAIL} --kind is `ontology` or `knowledge`, not {kind!r}")
        raise SystemExit(1)
    view, noun = _KIND_VIEWS[kind]
    tree_list = [Path(r).expanduser() for r in trees.split(":") if r] or plugins.effective_trees()
    idx = view(*tree_list)
    if target:
        targets = _test_targets(idx, target, noun)
    elif kind:
        meta = idx.metaontology_path
        targets = ([meta] if meta else []) + [p for p in idx.all_targets() if p != meta]
    else:
        targets = None
    if closure and targets is not None:
        full = NfxIndex(*tree_list)
        expanded = []
        for path in targets:
            try:
                expanded += full.closure(path, include_self=True)
            except exceptions.NfxViolation:
                expanded.append(path)  # reported against the document by `run_tests`
        targets = list(dict.fromkeys(expanded))
    neurobase.clear(c, confirmed=True)
    with NeuroBase() as nb:
        records = run_tests(nb, tree_list, targets)
    if out:
        Path(out).write_text(json.dumps(records, indent=2, default=str))
    report_tests(records, fmt)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")], help={
    "target": "Documents to test, comma-separated (stem, name, nid or path; `namespace` = the declarations). "
              "Default: everything.",
    "trees": "Colon-separated trees to read instead of this environment's PLUGINS",
    "fmt": "`json`: one record per document on stdout",
    "out": "Also write the records as JSON to this file (what `nfx.release` reads)",
    "closure": "Also test everything the targets depend on, not only load it",
    "kind": "`ontology` or `knowledge`: resolve targets among that kind only; with no target, test all of it",
})
def test(c, target="", trees="", fmt="text", out="", closure=False, kind=""):
    """Test .nfx documents in the test base. What is loaded for a document is its whole
    dependency closure, whatever the types in it; how it is judged goes by its type: an
    ontology's schema and validator tests, a knowledge document's values, a namespace's
    declaration."""
    run_test_task(c, target, trees, fmt, out, closure, kind)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def render(c, name=""):
    """Load an .nfx (ontology, knowledge, or metaontology) and its dependencies
    into neurobase and print the Neo4j browser link. Without --name, renders
    every discovered .nfx."""
    neurobase.start(c)
    idx = NfxIndex(*plugins.effective_trees())

    targets = resolve_target(idx, name, kind="Nfx")
    if not targets:
        print(f"{terminal_style.WARN} No .nfx files found.")
        return

    with NeuroBase() as nb:
        nb.clear(confirm=True)
        loaded = set()
        for path in targets:
            load_closure(nb, idx, path, loaded)

    print_browser_url()


# ---- what the base holds: info ---------------------------------------------------------

# `ontology.info` and `knowledge.info` are `nfx.info --kind …`: the metadata
# label a kind anchors on, what its modules are called, and what they define.
_INFO_KINDS = {
    "": ("Metadata+", "modules", "nodes"),
    "ontology": ("OntologyMetadata", "ontologies", "types"),
    "knowledge": ("KnowledgeMetadata", "knowledge modules", "nodes"),
}


def _info_label(nb, kind):
    """The label to match a kind's metadata on. `:Metadata+` needs the class in
    the base's ontology, and a base with no metaontology loaded has none: name
    the two anchors outright there, so the task reports an empty base rather
    than failing on it."""
    label = _INFO_KINDS[kind][0]
    try:
        nb.expand(f"MATCH (m:{label}) RETURN m")
    except LabelExpansionError:
        return "OntologyMetadata|KnowledgeMetadata"
    return label


def loaded_modules(nb, kind=""):
    """One row per module of `kind` loaded in the base (every kind when empty),
    with what it defines and its direct dependencies, of whatever kind."""
    label = _info_label(nb, kind)
    return nb.get_data(f"""
        MATCH (m:{label})
        OPTIONAL MATCH (m)-[:DEPENDS_ON]->(d)
        OPTIONAL MATCH (m)-[:DEFINES]->(n)
        RETURN m.nid AS nid, m.namespace AS namespace, m.name AS name,
               m.version AS version, m.type AS type,
               count(DISTINCT n) AS defined,
               collect(DISTINCT {{nid: d.nid, namespace: d.namespace, name: d.name}}) AS dependencies
        ORDER BY m.namespace, m.name
    """)


@contextlib.contextmanager
def _quiet_notifications():
    """Silence the driver's notifications for the queries inside. A base that
    holds no module yet has none of the labels, relationship types or property
    keys these queries name, and the server says so once for each of them -
    a screenful of warnings in front of the one line that answers."""
    logger = logging.getLogger("neo4j.notifications")
    level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(level)


def print_info(nb, kind=""):
    """The body of `nfx.info`, callable from the per-kind shortcuts: the
    modules loaded in the base as a table."""
    if kind not in _INFO_KINDS:
        print(f"{terminal_style.FAIL} --kind is `ontology` or `knowledge`, not {kind!r}")
        raise SystemExit(1)
    _, plural, counted = _INFO_KINDS[kind]
    with _quiet_notifications():
        label = _info_label(nb, kind)
        data = loaded_modules(nb, kind)
        if not data:
            print(f"{terminal_style.WARN} No {plural} loaded in `{os.getenv('BASE_NAME')}`.")
            return
        total = nb.get_data(f"MATCH (m:{label})-[:DEFINES]->(n) RETURN count(DISTINCT n) AS defined")[0]["defined"]
    # A name is unique inside its tree only: one row per module (by nid),
    # its tree beside it, and dependencies by their qualified names.
    rows = []
    for r in data:
        deps = ", ".join(sorted(Ontology.qualified_name(d) for d in r["dependencies"] if d["name"]))
        namespace = "-" if r["namespace"] is None else (r["namespace"] or "·")
        # every kind at once: say which each row is
        kind_cell = () if kind else (r["type"] or "",)
        rows.append((namespace, r["name"], *kind_cell, r["version"], str(r["defined"]), deps))
    header = ("Namespace", "Name", *(() if kind else ("Type",)), "Version", counted.capitalize(), "Dependencies")
    terminal_components.table(rows, header=header)
    print(f"\n{len(data)} {plural}, {total} {counted}")


@invoke.task(name="import", pre=[setup.env], help={
    "target": "The module to import: stem, name, qualified name, nid or path",
    "kind": "`ontology` or `knowledge`: refuse a module of the other kind",
})
def import_(c, target, kind=""):
    """Import one .nfx module into the base, with the dependencies the base lacks -
    ontology, knowledge or the metaontology alike. A node the module stops declaring
    is released, and deleted only when nothing is left on it; an edge, a label or a
    property is taken back when the module's previous release declared it and this
    one does not. Modules that pin what was written are listed, never re-imported."""
    run_import_task(target, kind)


@invoke.task(pre=[setup.env], help={
    "kind": "`ontology` or `knowledge`: only that kind's modules",
})
def info(c, kind=""):
    """What is loaded in the base, not on disk: one row per module - ontology, knowledge
    or metaontology - with its namespace, version, what it defines and what it depends on."""
    with NeuroBase() as nb:
        print_info(nb, kind)


# ---- a module in its tree: release, rename, move, log -------------------


@invoke.task(pre=[setup.env], help={
    "target": "Modules to release, comma-separated (stem, name, nid or path)",
    "tree": "The tree that holds them (default: found through PLUGINS)",
    "no-test": "Skip `nfx.test` on the release (schema, values, validator tests in the test base)",
})
def release(c, target, tree="", major=False, dry_run=False, message="", no_test=False):
    """Release documents (comma-separated) with their in-tree dependants: re-pin, bump, one commit, one tag each. An edited validators or test file of a released module goes into the same commit. The release is tested first (`nfx.test`) and refused on a failure."""
    targets = [nf_common.key(t, tree) for t in target.split(",") if t.strip()]
    repo = nf_common.repo(tree or nf_common.owner_tree(targets[0]))
    others = plugins.effective_trees()
    try:
        steps = repo.plan_release(targets, major, others) if dry_run else None
        if not dry_run:
            sha, steps, tags = repo.release(targets, major, others, message or None,
                                            gate=None if no_test else nf_common.test_gate(repo, others))
    except ValueError as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")
    except nf_repo.ReleaseRefused as e:
        nf_common.refused("release", e.issues)
    rows = [("●" if s.seed else "↳", str(s.rel), f"{s.old} → {s.new}", ", ".join(s.repins),
             "unreleased edits" if s.carries else "") for s in steps]
    terminal_components.table(rows, header=("", "Document", "Version", "Re-pins", "Also carries"))
    if dry_run:
        print(f"\n{len(steps)} document(s) would be released - dry run, nothing written")
        return
    print(f"\n{terminal_style.SUCCESS} {sha[:7]} released {len(steps)} document(s) · {len(tags)} tag(s)")


@invoke.task(pre=[setup.env])
def rename(c, target, new, tree="", dry_run=False):
    """Rename a module inside its tree: files, name, test path and tags in one `REFACTOR:` commit - a release like any change: next version, dependants re-pinned."""
    target = nf_common.key(target, tree)
    repo = nf_common.repo(tree or nf_common.owner_tree(target))
    try:
        plan = repo.plan_rename(target, new)
        if not dry_run:
            sha, plan = repo.rename(target, new, plugins.effective_trees())
    except (ValueError, RuntimeError) as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")
    except nf_repo.ReleaseRefused as e:
        nf_common.refused("rename", e.issues)
    rows = [(repo.show(a), repo.show(b)) for a, b in plan.files] + list(plan.tags)
    terminal_components.table(rows, header=("From", "To"))
    if dry_run:
        print(f"\n{plan.event.subject} - dry run, nothing written")
        return
    print(f"\n{terminal_style.SUCCESS} {sha[:7]} {plan.event.subject} · {len(plan.tags)} tag(s) moved")
    print(f"{terminal_style.DIM}pushed already? the remote still has the old tags: "
          f"git push <remote> {' '.join(f':refs/tags/{a}' for a, _ in plan.tags)} "
          f"{' '.join(f'refs/tags/{b}' for _, b in plan.tags)}{terminal_style.RESET}")


@invoke.task(name="move", pre=[setup.env], help={
    "to": "The tree it goes to: a path or a namespace token",
    "tree": "The tree it leaves (default: found through PLUGINS)",
})
def move_(c, target, to, tree="", with_dependants=False, as_="", dry_run=False):
    """Move a module into another tree: one `MIGRATE:` commit at each end, history left where it was."""
    target = nf_common.key(target, tree)
    source = nf_common.repo(tree or nf_common.owner_tree(target))
    dest = nf_common.repo(to)
    others = plugins.effective_trees()
    try:
        if dry_run:
            plan = nf_repo.plan_move(source, dest, target, with_dependants, as_, others)
        else:
            plan, departed, arrived = nf_repo.move(source, dest, target, with_dependants, as_, others)
    except (ValueError, RuntimeError) as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")
    except nf_repo.ReleaseRefused as e:
        nf_common.refused("move", e.issues)
    rows = [(source.show(a), dest.show(b), item.version, item.released or "never released")
            for item in plan.items for a, b in item.files]
    terminal_components.table(rows, header=("From", "To", "Version", "Released as"))
    if dry_run:
        print(f"\n{plan.departure_message.splitlines()[0]} - dry run, nothing written")
        return
    print(f"\n{terminal_style.SUCCESS} {source.root}: {departed[:7]} {plan.departure_message.splitlines()[0]}")
    print(f"{terminal_style.SUCCESS} {dest.root}: {arrived[:7]} {plan.arrival_message.splitlines()[0]}")


@invoke.task(name="log", pre=[setup.env], help={
    "tree": "The tree that holds it (default: found through PLUGINS)",
    "trees": "More trees to follow the history into, comma-separated paths, before PLUGINS",
})
def log_(c, target, tree="", trees=""):
    """A module's whole history, newest first, across its renames and moves - its own changes plain, a commit that only re-pins a dependency dimmed. `namespace` (or `namespace.nfx`): the declaration's history, in --tree or the tree you are in."""
    target = nf_common.key(target, tree or target.strip().removesuffix(".nfx") == "namespace")
    extra = [Path(r).expanduser() for r in trees.split(",") if r.strip()]
    try:
        if target == Path(nfx.NAMESPACE_FILENAME).stem:
            entries, note = nf_repo.namespace_log(nf_common.repo(tree)), None
        else:
            repo = nf_common.repo(tree or nf_common.owner_tree(target))
            entries, note = nf_repo.module_log(repo, target, trees=[*extra, *plugins.effective_trees()])
    except (ValueError, RuntimeError) as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")

    def dim(e, cells):
        # cell by cell: the table pads and cuts each cell on its own
        return tuple(f"{terminal_style.DIM}{v}{terminal_style.RESET}" if e.repin and v else v for v in cells)

    # the subject sits before the tags and runs over that column where a commit has none
    # Via: blank for a commit read in the tree asked, `linked` for one read in another, through a move
    rows = [dim(e, (e.date, e.token or nf_common.ROOT_MARK, e.via, e.sha[:7], e.version, e.subject,
                    ", ".join(e.tags)))
            for e in entries]
    terminal_components.table(rows, header=("Date", "Tree", "Via", "Commit", "Version", "Subject", "Tags"), shrink=5)
    repins = sum(e.repin for e in entries)
    if repins:
        print(f"\n{terminal_style.DIM}{repins} of {len(entries)} commit(s) only re-pin a dependency{terminal_style.RESET}")
    if note:
        print(f"\n{terminal_style.WARN} {note}")
