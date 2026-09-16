import dataclasses
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import invoke

from neuro.base import NeuroBase, nfx, plugins
from neuro.base.index import OntologyIndex
from neuro.utils import exceptions, internal_utils, terminal_components, terminal_style
from tasks.actions import setup
from tasks.components import neurobase, nfx as nfx_tasks


def _plugin_test_path(ontology_path):
    """Return a co-located `test_validators.py` path for an ontology, if any."""
    candidate = Path(ontology_path).parent / "test_validators.py"
    return candidate if candidate.exists() else None


def _document_failures(idx, path):
    """Return defects of the `.nfx` document itself, the same set the pre-commit
       hook rejects. Must run before import: MERGE collapses duplicates away.
    """
    raw = json.loads(Path(path).read_text())
    doc = nfx.Nfx.from_dict(raw)

    def resolve(nid):
        dep_path = idx.resolve(nid)
        return nfx.read(dep_path) if dep_path else None

    try:
        tree = nfx.NfxTree(doc, resolve)
    except exceptions.NfxCycle as e:
        return [f"dependency cycle {' → '.join(e.args[0])}"]
    report = nfx.validate(doc, dependency_nids=tree.all_node_nids(scope="dependencies"))
    lint = nfx.lint_format(raw)

    failures = []
    for bad in report["invalid_nids"]:
        failures.append(f"invalid nid {bad} (not UUID v4)")
    for r in report["unresolved"]:
        failures.append(f"unresolved {r.get('type', '?')} {r['from']} → {r['to']}")
    for r in report["foreign"]:
        failures.append(f"foreign {r.get('type', '?')} {r['from']} → {r['to']} (both endpoints external)")
    for nid in report["duplicate_nids"]:
        failures.append(f"duplicate node nid {nid}")
    for r in report["duplicate_relationships"]:
        failures.append(f"duplicate {r.get('type', '?')} {r['from']} → {r['to']}")
    for f in report["missing_required"]:
        failures.append(f"missing required top-level field {f!r}")
    if report["invalid_type"]:
        failures.append(f"type {report['invalid_type']!r} not in {list(nfx.ALLOWED_TYPES)}")
    for u in lint["unknown_keys"]:
        failures.append(f"{u['where']} has unknown keys {u['keys']}")
    for ko in lint["key_order"]:
        failures.append(f"{ko['where']} key order {ko['keys']} not canonical")
    for f in lint["empty"]:
        failures.append(f"{f!r} is empty — omit the key instead")
    return failures



@invoke.task(name="import", pre=[setup.env])
def import_(c, ontology=""):
    """Import ontology into neurobase. -o/--ontology required."""
    if not ontology:
        print(f"{terminal_style.FAIL} -o/--ontology required")
        raise SystemExit(1)
    ontology_dirs = internal_utils.get_path_list("PLUGINS")
    idx = OntologyIndex(*ontology_dirs)

    targets = nfx_tasks.resolve_target(idx, ontology, kind="Ontology")
    written = set()
    with NeuroBase() as nb:
        for path in targets:
            doc = nfx.read(path)
            name = doc.name or path.stem
            fresh = []
            with terminal_components.step(name) as status:
                log_dep = nfx_tasks.make_dep_logger(status)

                def on_import(dep_name, imported, depth=1, _fresh=fresh):
                    if imported:
                        _fresh.append(dep_name)
                    log_dep(dep_name, imported, depth)

                report = nb.metaontology.import_nfx(path, index=idx, on_import=on_import)
                nfx_tasks.print_import_report(status, report)
            written.add(doc.nid)
            for dep_name in fresh:
                dep_path = idx.resolve(dep_name)
                if dep_path:
                    written.add(nfx.read(dep_path).nid)
        nfx_tasks.print_orphan_hint(nb)
    nfx_tasks.print_dependant_hint(idx, written - {None, ""})


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def render(c, ontology="", independent=False, bare=False, dependants=False):
    """Load ontology into neurobase and print Neo4j browser link. --independent: without dependencies. --bare: skip property nodes. --dependants: also load ontologies that depend on target."""
    neurobase.start(c)
    ontology_dirs = internal_utils.get_path_list("PLUGINS")
    idx = OntologyIndex(*ontology_dirs)

    targets = nfx_tasks.resolve_target(idx, ontology, kind="Ontology")
    with NeuroBase() as nb:
        nb.clear(confirm=True)

        for path in targets:
            name = nfx.read(path).name or path.stem
            with terminal_components.step(name):
                if independent:
                    nb.nodes.import_nfx(path, validate=False)
                else:
                    nb.metaontology.import_nfx(path, index=idx)

        if ontology and not independent:
            target_doc = nfx.read(targets[0])
            target_nid = target_doc.nid
            target_name = target_doc.name or targets[0].stem
            _tag_dependencies(nb, target_name)
            if dependants:
                dependant_paths = _dependant_paths(idx, targets[0], target_nid)
                if dependant_paths:
                    with terminal_components.step("Dependants") as status:
                        for p in dependant_paths:
                            dep_name = nfx.read(p).name or p.stem
                            status.log(f"  ▸ {dep_name}")
                            nb.metaontology.import_nfx(p, index=idx)
                _tag_dependants(nb, target_name)

        if bare:
            _strip_properties(nb)

    nfx_tasks.print_browser_url()


def _tag_dependencies(nb, target_name):
    """Label objects defined by dependency ontologies (direct or transitive) with :Dependency. Metaontology and OntologyMetadata nodes are skipped."""
    nb.run_query(
        """
        MATCH (target:OntologyMetadata {name: $target_name})
        MATCH (target)-[:DEPENDS_ON*1..]->(dep:OntologyMetadata)
        WHERE dep.name <> "Metaontology"
        MATCH (dep)-[:DEFINES]->(n)
        WHERE NOT n:OntologyMetadata
        SET n:Dependency
        """,
        {"target_name": target_name},
    )


def _tag_dependants(nb, target_name):
    """Label objects defined by ontologies that directly depend on target with :Dependant."""
    nb.run_query(
        """
        MATCH (target:OntologyMetadata {name: $target_name})
        MATCH (dep:OntologyMetadata)-[:DEPENDS_ON]->(target)
        MATCH (dep)-[:DEFINES]->(n)
        WHERE NOT n:OntologyMetadata
        SET n:Dependant
        """,
        {"target_name": target_name},
    )


def _dependant_paths(idx, target_path, target_nid):
    """Return paths of ontologies that directly depend on target."""
    paths = []
    for p in idx.all_targets():
        if p == target_path:
            continue
        if target_nid in nfx.read(p).dep_nids:
            paths.append(p)
    return paths


@invoke.task(pre=[setup.env])
def index(c, tree=False, ontology=""):
    """Show discovered ontologies from PLUGINS search path. --tree: dependency graph. -o/--ontology: ontology details."""
    ontology_dirs = internal_utils.get_path_list("PLUGINS")
    idx = OntologyIndex(*ontology_dirs)

    if ontology:
        _index_info(idx, ontology)
        return
    if tree:
        _index_tree(idx)
        return

    app_dir = Path(os.environ["APP_DIR"])
    rows = []
    for path in idx.all_targets():
        doc = nfx.read(path)
        try:
            rel = os.path.relpath(path, app_dir)
        except ValueError:
            rel = str(path)
        rows.append((
            doc.name or path.stem,
            doc.version,
            (doc.nid or "")[:8],
            rel,
        ))
    rows.sort(key=lambda r: (r[0] != "Metaontology", r[0]))
    header = ("Name", "Version", "NID", "Path")
    terminal_components.table(rows, header=header)


def _strip_properties(nb):
    """Remove all property nodes (targets of HAS_PROPERTY/REQUIRE_PROPERTY) from the database."""
    nb.run_query("MATCH ()-[:HAS_PROPERTY|REQUIRE_PROPERTY]->(p) DETACH DELETE p")


def _index_info(idx, ontology_name):
    """Show detailed info about a single ontology from NFX files."""
    path = idx.resolve(ontology_name)
    if not path:
        print(f"{terminal_style.FAIL} Ontology not found: {ontology_name}")
        raise SystemExit(1)

    doc = nfx.read(path)
    B, RST, DIM = terminal_style.BOLD, terminal_style.RESET, terminal_style.DIM

    # Header
    print(f"\n{B}{doc.name or path.stem}{RST} {DIM}v{doc.version or '?'}{RST}")
    print("-" * 50)
    if doc.description:
        print(f"  {doc.description}")
    print(f"  {DIM}{doc.nid or '?'}{RST}")
    print(f"  {DIM}{path}{RST}")

    # Types
    ontology_objects = json.loads(os.environ["ONTOLOGY_OBJECTS"])
    types = [n for n in doc.nodes if any(lb in ontology_objects for lb in n.get("labels", []))]
    non_types = [n for n in doc.nodes if not any(lb in ontology_objects for lb in n.get("labels", []))]

    kind_map = {"OntologyNode": "Nodes", "OntologyRelationship": "Relationships"}
    by_kind = {}
    for t in types:
        kind = next((lb for lb in t.get("labels", []) if lb in ontology_objects), "")
        by_kind.setdefault(kind, []).append(t.get("properties", {}).get("label", "?"))

    total = len(types) + len(non_types)
    print(f"\nObjects ({total}):")
    for kind in sorted(by_kind):
        labels = sorted(by_kind[kind])
        heading = kind_map.get(kind, kind)
        print(f"  {DIM}{heading}{RST}:  {', '.join(labels)}")
    if non_types:
        print(f"  {DIM}Properties{RST}:  {len(non_types)}")

    # Dependencies
    nfx_tasks.print_dependencies(idx, doc)

    # Dependants
    dependants = []
    for p in idx.all_targets():
        if p == path:
            continue
        other = nfx.read(p)
        if doc.nid in other.dep_nids:
            dependants.append(other.name or p.stem)
    if dependants:
        print("\nRequired by:")
        for name in sorted(dependants):
            print(f"  {name}")

    # Release history
    history = _version_history(path)
    if history:
        print("\nReleases:")
        terminal_components.table(history, header=("Version", "Date"))
    print()


def _version_history(path):
    """Extract (version, date) pairs from git tags '<name>/<version>' across all PLUGINS repos."""
    name = (nfx.read(path).name or Path(path).stem).lower()
    repos = set()
    for d in internal_utils.get_path_list("PLUGINS"):
        try:
            root = subprocess.run(
                ["git", "-C", str(d), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        repos.add(root)

    history = []
    for root in repos:
        result = subprocess.run(
            ["git", "-C", root, "for-each-ref",
             "--format=%(refname:lstrip=3)|%(creatordate:short)",
             f"refs/tags/{name}/"],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.splitlines():
            version, _, date = line.partition("|")
            if version and date:
                history.append((version, date))
    history.sort(key=lambda r: [int(p) if p.isdigit() else p for p in r[0].split(".")])
    return history


def _index_tree(idx):
    """Print a dependency tree from NFX file metadata (no DB needed)."""
    packages = {}
    for path in idx.all_targets():
        doc = nfx.read(path)
        packages[doc.nid] = {
            "name": doc.name or path.stem,
            "version": doc.version,
            "dep_nids": list(doc.dep_nids),
        }

    # Find roots: packages that no other package depends on
    all_deps = {d for p in packages.values() for d in p["dep_nids"]}
    roots = [nid for nid in packages if nid not in all_deps]

    def _draw(nid, prefix="", is_last=True):
        p = packages[nid]
        connector = "└── " if is_last else "├── "
        print(f"{prefix}{connector}{p['name']}@{p['version']}")
        child_prefix = prefix + ("    " if is_last else "│   ")
        children = [d for d in p["dep_nids"] if d in packages]
        for i, dep_nid in enumerate(sorted(children, key=lambda d: packages[d]["name"])):
            _draw(dep_nid, child_prefix, i == len(children) - 1)

    for i, nid in enumerate(sorted(roots, key=lambda n: packages[n]["name"])):
        p = packages[nid]
        print(f"{p['name']}@{p['version']}")
        children = [d for d in p["dep_nids"] if d in packages]
        for j, dep_nid in enumerate(sorted(children, key=lambda d: packages[d]["name"])):
            _draw(dep_nid, "", j == len(children) - 1)


def _ontology_tree(nb):
    """Print the dependency graph as an ASCII tree."""
    data = nb.get_data("""
        MATCH (m:OntologyMetadata)
        OPTIONAL MATCH (m)-[:DEPENDS_ON]->(d:OntologyMetadata)
        RETURN m.name as name, m.version as version,
               collect(DISTINCT d.name) as dependencies
    """)
    by_name = {r["name"]: r for r in data}
    roots = [r["name"] for r in data
             if not any(r["name"] in d["dependencies"] for d in data)]

    def _draw(name, prefix="", is_last=True):
        r = by_name[name]
        connector = "└── " if is_last else "├── "
        print(f"{prefix}{connector}{r['name']}@{r['version']}")
        child_prefix = prefix + ("    " if is_last else "│   ")
        deps = sorted(r["dependencies"])
        for i, dep in enumerate(deps):
            _draw(dep, child_prefix, i == len(deps) - 1)

    for i, root in enumerate(sorted(roots)):
        r = by_name[root]
        print(f"{r['name']}@{r['version']}")
        deps = sorted(r["dependencies"])
        for j, dep in enumerate(deps):
            _draw(dep, "", j == len(deps) - 1)


@invoke.task(pre=[setup.env])
def info(c, type="", tree=False):
    """Show ontology info. Without --type: loaded ontologies overview. With --type: type details. With --tree: dependency graph."""
    with NeuroBase() as nb:
        if type:
            try:
                nb.ontology.info(type).display()
            except ValueError as e:
                print(f"{terminal_style.FAIL} {e}")
                raise SystemExit(1)
        elif tree:
            _ontology_tree(nb)
        else:
            data = nb.get_data("""
                MATCH (m:OntologyMetadata)
                OPTIONAL MATCH (m)-[:DEPENDS_ON]->(d:OntologyMetadata)
                OPTIONAL MATCH (m)-[:DEFINES]->(n)
                RETURN m.name as name, m.version as version,
                       count(DISTINCT n) as types,
                       collect(DISTINCT d.name) as dependencies
                ORDER BY m.name
            """)
            rows = []
            for r in data:
                deps = ", ".join(sorted(r["dependencies"])) if r["dependencies"] else ""
                rows.append((r["name"], r["version"], str(r["types"]), deps))
            header = ("Name", "Version", "Types", "Dependencies")
            terminal_components.table(rows, header=header)

            total = nb.get_data("""
                MATCH (m:OntologyMetadata)-[:DEFINES]->(n)
                RETURN count(DISTINCT n) as types
            """)[0]
            print(f"\n{len(data)} ontologies, {total['types']} types")


@invoke.task(pre=[setup.env])
def export(c, path):
    """Export ontology from neurobase to an NFX file."""
    with NeuroBase() as nb:
        nb.ontology.export_nfx(path)


@invoke.task(pre=[setup.env])
def count(c):
    """Count all ontology nodes in the database."""
    with NeuroBase() as nb:
        print(nb.ontology.count())


@invoke.task(pre=[setup.env])
def clear(c):
    """Remove all ontology nodes from the database."""
    if os.environ.get("ENV") == "PRODUCTION":
        if not terminal_components.bool_prompt(
            f"{terminal_style.WARN} ENV=PRODUCTION. Really clear ontology?",
            default=False,
        ):
            raise SystemExit("Aborting clear.")
    with NeuroBase() as nb:
        nb.ontology.clear()


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, o="", fmt="text"):
    """Validate each ontology against the metaontology and run its plugin
       validators together. -o: target file. --fmt json: one machine-readable
       record per ontology (path, outcome, duration, failures) on stdout.
    """
    neurobase.clear(c, confirmed=True)
    ontology_dirs = internal_utils.get_path_list("PLUGINS")
    idx = OntologyIndex(*ontology_dirs)
    metaontology_nid = nfx.read(idx.metaontology_path).nid
    if o:
        target_path = idx.resolve(o)
        if not target_path:
            print(f"{terminal_style.FAIL} Ontology not found: {o}")
            raise SystemExit(1)
        targets = nfx_tasks.topo_targets(idx, target_path, metaontology_nid)
    else:
        targets = [idx.metaontology_path] + list(idx.all_targets(exclude_nid=metaontology_nid))

    pytest_bin = os.path.join(setup.get_nenv_dir(), "bin", "pytest")
    failed = []
    # One record per ontology, so a consumer can say *which* one broke and how
    # long it took. The text rendering below is unchanged; --fmt json adds the
    # machine-readable form rather than replacing it, because parsing ✔/✘ off a
    # terminal-styled stdout is not a contract anyone should depend on.
    report = []
    with NeuroBase() as nb:
        for path in targets:
            doc = nfx.read(path)
            name = doc.name or path.stem
            started = time.monotonic()

            failures = _document_failures(idx, path)
            warnings = []

            if not failures:
                nb.clear(confirm=True)
                nb.metaontology.import_nfx(path, index=idx)
                nb.metaontology.is_ontology_valid()
                failures.extend(str(v) for v in nb.metaontology.violations)
                failures.extend(str(err) for err in idx.check_dependency_versions(path))
                warnings = list(nb.metaontology.violations.warnings)

                test_path = _plugin_test_path(path)
                if test_path:
                    result = subprocess.run(
                        [pytest_bin, "--import-mode=importlib", str(test_path)],
                        capture_output=True, text=True,
                    )
                    if result.returncode != 0:
                        output = (result.stdout + result.stderr).rstrip()
                        if output:
                            failures.append(output)
                        else:
                            failures.append(f"pytest failed (exit {result.returncode})")

            report.append({
                "name": name,
                "path": str(path),
                "outcome": "failed" if failures else "passed",
                "duration_s": round(time.monotonic() - started, 3),
                "failure_count": len(failures),
                "failures": failures,
                "warnings": [str(w) for w in warnings],
            })

            if fmt == "text":
                if failures:
                    print(f"{terminal_style.FAIL} {name}")
                    for entry in failures:
                        for line in entry.splitlines():
                            print(f"  {line}")
                else:
                    print(f"{terminal_style.SUCCESS} {name}")
                for w in warnings:
                    print(f"  {w}")
            if failures:
                failed.append(name)

    if fmt == "json":
        print(json.dumps(report, indent=2, default=str))

    if failed:
        raise SystemExit(1)


@invoke.task(pre=[setup.env])
def rehash(c, ontology=""):
    """Recompute sha256(validators.py) and update the `hash` field in dir-form .nfx files. -o: target one ontology."""
    ontology_dirs = internal_utils.get_path_list("PLUGINS")
    idx = OntologyIndex(*ontology_dirs)
    targets = nfx_tasks.resolve_target(idx, ontology, kind="Ontology")

    touched = 0
    for path in targets:
        plugin_dir = plugins.plugin_dir_for(path)
        if plugin_dir is None:
            continue
        validators_path = plugin_dir / "validators.py"
        if not validators_path.is_file():
            continue
        current = hashlib.sha256(validators_path.read_bytes()).hexdigest()
        doc = nfx.read(path)
        if doc.hash == current:
            print(f"  {terminal_style.SKIP} {terminal_style.DIM}{path.name}  {current[:12]}…{terminal_style.RESET}")
            continue
        doc = dataclasses.replace(doc, hash=current)
        path.write_text(nfx.dumps(doc))
        print(f"  {terminal_style.SUCCESS} {path.name}  {current[:12]}…")
        touched += 1

    print(f"\n{touched} file(s) updated")


def _hold_reason(row):
    """Why a node survives a removal, in the operator's terms. Both halves are
    reported when both apply — an edge from outside is a different problem from
    a live instance, and the fix differs too."""
    reasons = []
    if row["held"]:
        reasons.append(f"{row['held']} rel(s) outside the ontology layer "
                       f"({', '.join(row['rel_types'])})")
    if row["instances"]:
        instances = f"{row['instances']} live instance(s)"
        # An instance names its class by label, and two ontologies may define
        # the same label under different nids — Sirin and Spectroscopy both
        # declare `Project`. Nothing on the instance says which node it means,
        # so the count is attributed to both and the class is kept either way.
        # Say when a surviving twin exists: it is usually the real owner, and
        # the operator is the only one who can tell.
        if row.get("twin"):
            instances += f" — label also defined by {', '.join(row['twin'])}, which stays"
        reasons.append(instances)
    return "; ".join(reasons)


@invoke.task(pre=[setup.env])
def prune(c, confirm=False):
    """Delete orphaned ontology nodes — ones no ontology defines any more.

    `ontology.import` releases a node it stops declaring rather than deleting
    it, because the set of edges reaching into the ontology layer is open and a
    delete severs edges no import restores (PLAN-2026-143). This is the
    deliberate removal path, and it is deliberately narrow: only orphans the
    wider graph has finished with are deleted — no relationship reaching them
    from outside the ontology layer, and no instances still carrying the class
    as a label. An orphan failing either test is reported and left alone; that
    is exactly the case a blanket delete would destroy silently.

    The narrowness is that guard and nothing else. Candidates come from
    `nfx.orphan_nodes`, which covers every `OntologyObject` subtype — classes,
    relationship types *and* properties. Enumerating the first two here once
    made a dropped property invisible to both this task and the hint that
    points at it (PLAN-2026-148).
    --confirm to actually delete.
    """
    with NeuroBase() as nb:
        rows = nfx_tasks.orphan_nodes(nb, with_edges=True)
    if not rows:
        print(f"{terminal_style.SUCCESS} No orphaned ontology nodes")
        return

    held = [r for r in rows if r["held"] or r["instances"]]
    free = [r for r in rows if not r["held"] and not r["instances"]]
    for r in held:
        print(f"  {terminal_style.WARN} {r['label']}  "
              f"{terminal_style.DIM}kept — {_hold_reason(r)}{terminal_style.RESET}")
    for r in free:
        print(f"  {terminal_style.SKIP} {r['label']}  "
              f"{terminal_style.DIM}{r['kind']} · {r['nid']}{terminal_style.RESET}")
    if held:
        print(f"\n{len(held)} orphan(s) kept: still in use by the wider graph.")
    if not free:
        return
    if not confirm:
        print(f"\n{len(free)} isolated orphan(s) would be deleted. Re-run with --confirm.")
        return
    with NeuroBase() as nb:
        nb.run_query("MATCH (n) WHERE n.nid IN $nids DETACH DELETE n",
                     {"nids": [r["nid"] for r in free]})
    print(f"\n{terminal_style.SUCCESS} {len(free)} isolated orphan(s) deleted")


def _graph_ontology(nb, key):
    """Resolve an ontology *in the base*, by nid or name.

    Deliberately not through `OntologyIndex`. The case this task exists for is
    an ontology whose files belong to a different base entirely, so the file
    index is the wrong authority for what this graph is holding — and reaching
    for it would make the stray closure unnameable by the one command meant to
    remove it.
    """
    rows = nb.get_data(
        """
        MATCH (m:OntologyMetadata)
        WHERE m.nid = $key OR toLower(m.name) = toLower($key)
        RETURN m.nid AS nid, m.name AS name, m.version AS version
        ORDER BY m.name
        """,
        {"key": key},
    )
    exact = [r for r in rows if r["nid"] == key or r["name"] == key]
    return (exact or rows or [None])[0]


def _depends_on_doomed(nb, doomed):
    """Anything outside the delete set still pointing at a metadata node inside
    it. An ontology that depends on the closure carries `SUBCLASS_OF` into it,
    so removing it leaves a class hierarchy whose upper half is gone.

    The keeper is deliberately unlabelled and the edge type deliberately
    unfiltered. `KnowledgeMetadata` pins its ontologies with the same
    `DEPENDS_ON` — `MetadataAccessor.upsert` writes both — so a check spelled
    `keeper:OntologyMetadata` would let an ontology be withdrawn out from under
    a loaded knowledge base, whose nodes are instances of exactly the classes
    about to go. Nothing else points at an `OntologyMetadata` node today;
    matching any edge means whatever does tomorrow gets reported instead of
    severed by the `DETACH DELETE`.
    """
    return nb.get_data(
        """
        MATCH (keeper)-[r]->(d:OntologyMetadata)
        WHERE d.nid IN $doomed AND NOT keeper.nid IN $doomed
        RETURN DISTINCT d.nid AS nid, d.name AS needed, type(r) AS rel,
               coalesce(keeper.name, keeper.label, keeper.nid) AS keeper,
               labels(keeper)[0] AS kind
        ORDER BY keeper, needed
        """,
        {"doomed": doomed},
    )


def _doomed_set(nb, target_nid, closure):
    """The `OntologyMetadata` nids this run removes.

    Without `--closure` that is the target alone. With it, the target plus every
    dependency nothing outside the set still needs — the `DEPENDS_ON` graph
    garbage-collected, the way a package manager drops the dependencies a
    removed package alone pulled in.

    Run to a fixed point, because rescuing one ontology rescues everything it in
    turn depends on. That is what separates a foreign root's own closure from
    the shared bases underneath it: withdrawing `Sbase` from a base whose own
    root still stands on `Metaontology`, `Math` and `Time` must take the first
    and leave the rest (INC-2026-009).

    The Metaontology is excluded outright rather than left to that walk. In a
    base holding nothing but the target's own closure there is no ontology
    outside the set to rescue it, so the collection would be correct and still
    wrong: taking the layer's root out from under everything is
    `ontology.clear`'s job, not a side effect of withdrawing one ontology.
    """
    if not closure:
        return [target_nid]
    rows = nb.get_data(
        """
        MATCH (t:OntologyMetadata {nid: $nid})-[:DEPENDS_ON*0..]->(d:OntologyMetadata)
        WHERE d.name <> "Metaontology"
        RETURN collect(DISTINCT d.nid) AS nids
        """,
        {"nid": target_nid},
    )
    doomed = set(rows[0]["nids"]) if rows and rows[0]["nids"] else {target_nid}
    while True:
        rescued = {r["nid"] for r in _depends_on_doomed(nb, sorted(doomed))}
        # The target is never rescued: a dependent of *it* is a blocker the
        # operator has to resolve, not a dependency this walk over-collected.
        rescued.discard(target_nid)
        if not rescued:
            return sorted(doomed)
        doomed -= rescued


# Fate of every node the doomed ontologies define, decided before anything is
# written. Same rule as `ontology.prune`: a node the wider graph still reaches
# is kept and reported, never deleted. `released` is carried forward so the
# outside-edge test is a comparison against nodes already in hand rather than a
# second scan, and so an edge *within* the doomed closure does not count as the
# wider graph holding on.
_RELEASED = """
    MATCH (m:OntologyMetadata)-[:DEFINES]->(n)
    WHERE m.nid IN $doomed
    WITH collect(DISTINCT n) AS released
    UNWIND released AS n
    WITH released, n,
         [(keeper:OntologyMetadata)-[:DEFINES]->(n)
          WHERE NOT keeper.nid IN $doomed | keeper.name] AS claimed_by
    OPTIONAL MATCH (n)-[r]-(o)
    WHERE NOT o IN released
      AND NOT any(lbl IN labels(o) WHERE lbl IN
            ['OntologyMetadata', 'KnowledgeMetadata'])
      AND NOT (o)<-[:DEFINES]-(:OntologyMetadata)
    RETURN n.nid AS nid, coalesce(n.label, n.nid) AS label,
           labels(n)[0] AS kind, claimed_by,
           count(r) AS held, collect(DISTINCT type(r))[0..4] AS rel_types
    ORDER BY label
"""


@invoke.task(pre=[setup.env])
def delete(c, ontology="", closure=False, confirm=False):
    """Remove one ontology from the base — its metadata node and the nodes it
    alone defines. -o/--ontology required (name or nid).

    The withdrawal path for an ontology that should not be in this base at all.
    Neither existing task can reach one: `ontology.import` only reconciles what
    a file declares, and `ontology.prune` only sweeps what nothing declares any
    more — a foreign closure is neither, because its own `DEFINES` edges are
    perfectly intact. So it sits in the graph, invisible to both
    (INC-2026-009, where `sip ontology.import -o sbase` wrote fourteen spectro
    ontologies into Sirin and no reconciling import could take them back out).

    --closure also removes the dependencies the target alone pulled in, keeping
    every one an ontology outside the set still depends on. --confirm to
    delete; without it the run only reports.

    A node is kept, never deleted, when another ontology still defines it, when
    the wider graph still reaches it, or when instances of the class are still
    in the base. That is `ontology.prune`'s guard, applied here for the same
    reason: a delete severs edges no import restores (PLAN-2026-143). Kept
    nodes outlive their ontology as orphans, which is a reported outcome and
    not a failure.
    """
    if not ontology:
        print(f"{terminal_style.FAIL} -o/--ontology required")
        raise SystemExit(1)

    with NeuroBase() as nb:
        target = _graph_ontology(nb, ontology)
        if not target:
            print(f"{terminal_style.FAIL} Ontology not in the base: {ontology}")
            raise SystemExit(1)
        if target["name"] == "Metaontology":
            print(f"{terminal_style.FAIL} Refusing to delete the Metaontology — "
                  f"every other ontology is defined in its terms. "
                  f"Use ontology.clear to wipe the layer.")
            raise SystemExit(1)

        doomed = _doomed_set(nb, target["nid"], closure)
        blocked = _depends_on_doomed(nb, doomed)
        if blocked:
            print(f"{terminal_style.FAIL} Still depended on by records that stay:")
            for r in blocked:
                print(f"    {r['keeper']} ({r['kind']}) -{r['rel']}→ {r['needed']}")
            print("\nThese are dependents, which --closure does not cover — it removes "
                  "dependencies. Withdraw them first, leaves before roots.")
            raise SystemExit(1)

        removing = nb.get_data(
            """
            MATCH (m:OntologyMetadata) WHERE m.nid IN $doomed
            RETURN m.name AS name, coalesce(m.version, '?') AS version
            ORDER BY m.name
            """,
            {"doomed": doomed},
        )
        rows = nb.get_data(_RELEASED, {"doomed": doomed})
        counts = nfx_tasks.instance_counts(nb, [r["label"] for r in rows])
        twins = {r["label"]: r["keepers"] for r in nb.get_data(
            """
            MATCH (keeper:OntologyMetadata)-[:DEFINES]->(n)
            WHERE NOT keeper.nid IN $doomed AND n.label IN $labels
            RETURN n.label AS label, collect(DISTINCT keeper.name) AS keepers
            """,
            {"doomed": doomed,
             "labels": sorted({r["label"] for r in rows if counts.get(r["label"])})},
        )}
        for r in rows:
            r["instances"] = counts.get(r["label"], 0)
            r["twin"] = twins.get(r["label"], [])

    reparented = [r for r in rows if r["claimed_by"]]
    rest = [r for r in rows if not r["claimed_by"]]
    held = [r for r in rest if r["held"] or r["instances"]]
    free = [r for r in rest if not r["held"] and not r["instances"]]

    print(f"{terminal_style.WARN} Removing "
          f"{len(removing)} ontolog{'y' if len(removing) == 1 else 'ies'}:")
    for m in removing:
        print(f"    {m['name']}@{m['version']}")

    for r in reparented:
        print(f"  {terminal_style.SKIP} {r['label']}  "
              f"{terminal_style.DIM}kept — also defined by "
              f"{', '.join(r['claimed_by'])}{terminal_style.RESET}")
    for r in held:
        print(f"  {terminal_style.WARN} {r['label']}  "
              f"{terminal_style.DIM}kept — {_hold_reason(r)}{terminal_style.RESET}")
    for r in free:
        print(f"  {terminal_style.SKIP} {r['label']}  "
              f"{terminal_style.DIM}{r['kind']} · {r['nid']}{terminal_style.RESET}")
    if held:
        print(f"\n{len(held)} node(s) kept: still in use by the wider graph. "
              f"Each outlives its ontology as an orphan.")

    if not confirm:
        print(f"\n{len(removing)} ontology record(s) and {len(free)} node(s) "
              f"would be deleted. Re-run with --confirm.")
        return

    if os.environ.get("ENV") == "PRODUCTION":
        if not terminal_components.bool_prompt(
            f"{terminal_style.WARN} ENV=PRODUCTION. Really delete {target['name']}?",
            default=False,
        ):
            raise SystemExit("Aborting delete.")

    with NeuroBase() as nb:
        # Metadata first: dropping it releases the `DEFINES` and `DEPENDS_ON`
        # edges, so the node sweep that follows deletes nodes nothing claims —
        # the same state `ontology.prune` operates on.
        nb.run_query("MATCH (m:OntologyMetadata) WHERE m.nid IN $doomed DETACH DELETE m",
                     {"doomed": doomed})
        if free:
            nb.run_query("MATCH (n) WHERE n.nid IN $nids DETACH DELETE n",
                         {"nids": [r["nid"] for r in free]})
        print(f"\n{terminal_style.SUCCESS} {len(removing)} ontology record(s) and "
              f"{len(free)} node(s) deleted")
        nfx_tasks.print_orphan_hint(nb)
