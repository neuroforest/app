import dataclasses
import hashlib
import json
import os
import subprocess
from pathlib import Path

import invoke

from neuro.base import NeuroBase, nfx, plugins
from neuro.base.index import OntologyIndex
from neuro.utils import internal_utils, terminal_components, terminal_style
from tasks.actions import setup
from tasks.components import neurobase, nfx as nfx_tasks


def _plugin_test_path(ontology_path):
    """Return a co-located `test_validators.py` path for an ontology, if any."""
    candidate = Path(ontology_path).parent / "test_validators.py"
    return candidate if candidate.exists() else None



@invoke.task(name="import", pre=[setup.env])
def import_(c, ontology=""):
    """Import ontology into neurobase. -o/--ontology required."""
    if not ontology:
        print(f"{terminal_style.FAIL} -o/--ontology required")
        raise SystemExit(1)
    ontology_dirs = internal_utils.get_path_list("PLUGINS")
    idx = OntologyIndex(*ontology_dirs)

    targets = nfx_tasks.resolve_target(idx, ontology, kind="Ontology")
    with NeuroBase() as nb:
        for path in targets:
            name = nfx.read(path).name or path.stem
            with terminal_components.step(name) as status:
                nb.metaontology.import_nfx(
                    path, index=idx, on_import=nfx_tasks.make_dep_logger(status),
                )


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
            f"{terminal_style.WARNING} ENV=PRODUCTION. Really clear ontology?",
            default=False,
        ):
            raise SystemExit("Aborting clear.")
    with NeuroBase() as nb:
        nb.ontology.clear()


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, o=""):
    """Validate each ontology against the metaontology and run its plugin
       validators together. -o: target file.
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
    with NeuroBase() as nb:
        for path in targets:
            doc = nfx.read(path)
            name = doc.name or path.stem

            failures = []
            warnings = []

            nb.clear(confirm=True)
            nb.metaontology.import_nfx(path, index=idx)
            nb.metaontology.is_ontology_valid()
            dep_errors = idx.check_dependency_versions(path)
            lint = nfx.lint_format(json.loads(path.read_text()))
            if (nb.metaontology.violations or dep_errors
                    or lint["unknown_keys"] or lint["key_order"] or lint["empty"]):
                failures.extend(str(v) for v in nb.metaontology.violations)
                failures.extend(str(err) for err in dep_errors)
                for u in lint["unknown_keys"]:
                    failures.append(f"{u['where']} has unknown keys {u['keys']}")
                for ko in lint["key_order"]:
                    failures.append(f"{ko['where']} key order {ko['keys']} not canonical")
                for f in lint["empty"]:
                    failures.append(f"{f!r} is empty — omit the key instead")
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

            if failures:
                print(f"{terminal_style.FAIL} {name}")
                for entry in failures:
                    for line in entry.splitlines():
                        print(f"  {line}")
                failed.append(name)
            else:
                print(f"{terminal_style.SUCCESS} {name}")
            for w in warnings:
                print(f"  {w}")

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
