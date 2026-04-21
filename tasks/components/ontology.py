import json
import os
import subprocess
from pathlib import Path

import invoke

from neuro.base import NeuroBase, nfx
from neuro.base.index import OntologyIndex
from neuro.base.ontology import ObjectValidator
from neuro.utils import internal_utils, terminal_components, terminal_style
from tasks.actions import setup
from tasks.components import neurobase



def _resolve_target(idx, ontology):
    """Resolve a single ontology target, or return all targets if empty."""
    if ontology:
        path = idx.resolve(ontology)
        if not path:
            print(f"{terminal_style.FAIL} Ontology not found: {ontology}")
            raise SystemExit(1)
        return [path]
    return idx.all_targets()


@invoke.task(name="import", pre=[setup.env])
def import_(c, ontology=""):
    """Import ontology into neurobase."""
    ontology_dirs = internal_utils.get_path_list("ONTOLOGY")
    idx = OntologyIndex(*ontology_dirs)

    targets = _resolve_target(idx, ontology)
    with NeuroBase() as nb:
        for path in targets:
            name = nfx.read(path).get("name", path.stem)
            with terminal_components.step(name) as status:
                def on_import(dep_name, imported):
                    status.log(f"  {'▸' if imported else '-'} {dep_name}{'' if imported else ' (loaded)'}")
                nb.metaontology.import_nfx(path, index=idx, on_import=on_import)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def render(c, ontology="", independent=False, bare=False):
    """Load ontology into neurobase and print Neo4j browser link. --independent: without dependencies. --bare: skip property nodes."""
    neurobase.start(c)
    ontology_dirs = internal_utils.get_path_list("ONTOLOGY")
    idx = OntologyIndex(*ontology_dirs)

    targets = _resolve_target(idx, ontology)
    with NeuroBase() as nb:
        nb.clear(confirm=True)

        for path in targets:
            name = nfx.read(path).get("name", path.stem)
            with terminal_components.step(name):
                if independent:
                    nb.nodes.import_nfx(path, validate=False)
                else:
                    nb.metaontology.import_nfx(path, index=idx)

        if bare:
            _strip_properties(nb)

    http_port = os.environ["NEO4J_PORT_HTTP"]
    print(f"\n  http://localhost:{http_port}/browser/")


def _validate_instances(nb, path):
    """Validate instance nodes in an NFX file against the loaded ontology."""

    class _Node:
        def __init__(self, labels, properties):
            self.labels = labels
            self.properties = properties

    data = nfx.read(path)
    ontology_labels = set(json.loads(os.environ["ONTOLOGY_OBJECTS"]))
    failed = []

    for entry in data.get("nodes", []):
        if any(label in ontology_labels for label in entry["labels"]):
            continue
        props = {"neuro.id": entry["nid"], **entry.get("properties", {})}
        node = _Node(entry["labels"], props)
        violations = ObjectValidator(nb, node).get_violations()
        if violations:
            identifier = (
                entry.get("properties", {}).get("identifier")
                or entry.get("properties", {}).get("name")
                or entry["nid"]
            )
            failed.append((identifier, ":".join(entry["labels"]), violations))

    for identifier, label_str, violations in failed:
        print(f"  {terminal_style.FAIL} {label_str} {identifier}")
        print(f"  {repr(violations)}")

    return not failed


@invoke.task(pre=[setup.env])
def index(c, tree=False, ontology=""):
    """Show discovered ontologies from ONTOLOGY search path. --tree: dependency graph. -o/--ontology: ontology details."""
    ontology_dirs = internal_utils.get_path_list("ONTOLOGY")
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
        data = nfx.read(path)
        try:
            rel = os.path.relpath(path, app_dir)
        except ValueError:
            rel = str(path)
        rows.append((
            data.get("name", path.stem),
            data.get("version", ""),
            data.get("nid", ""),
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

    data = nfx.read(path)
    B, RST, DIM = terminal_style.BOLD, terminal_style.RESET, terminal_style.DIM

    # Header
    print(f"\n{B}{data.get('name', path.stem)}{RST} {DIM}v{data.get('version', '?')}{RST}")
    print("-" * 50)
    desc = data.get("description", "")
    if desc:
        print(f"  {desc}")
    print(f"  {DIM}{data.get('nid', '?')}{RST}")
    print(f"  {DIM}{path}{RST}")

    # Types
    ontology_objects = json.loads(os.environ["ONTOLOGY_OBJECTS"])
    nodes = data.get("nodes", [])
    types = [n for n in nodes if any(lb in ontology_objects for lb in n.get("labels", []))]
    non_types = [n for n in nodes if not any(lb in ontology_objects for lb in n.get("labels", []))]

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
    deps = data.get("dependencies", [])
    if deps:
        print("\nDependencies:")
        for dep in deps:
            dep_nid, _, dep_ver = dep.partition("@")
            dep_path = idx.resolve(dep_nid)
            if dep_path:
                dep_data = nfx.read(dep_path)
                dep_name = dep_data.get("name", dep_path.stem)
                actual_ver = dep_data.get("version", "?")
                if actual_ver == dep_ver:
                    print(f"  {terminal_style.SUCCESS} {dep_name}@{dep_ver}")
                else:
                    print(f"  {terminal_style.FAIL} {dep_name}@{dep_ver} (found {actual_ver})")
            else:
                print(f"  {terminal_style.FAIL} {dep_nid}@{dep_ver} (not found)")

    # Dependants
    target_nid = data.get("nid", "")
    dependants = []
    for p in idx.all_targets():
        if p == path:
            continue
        other = nfx.read(p)
        for dep in other.get("dependencies", []):
            dep_nid, _, _ = dep.partition("@")
            if dep_nid == target_nid:
                dependants.append(other.get("name", p.stem))
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
    """Extract (version, date) pairs from git tags '<name>/<version>' across all ONTOLOGY repos."""
    name = nfx.read(path).get("name", Path(path).stem).lower()
    repos = set()
    for d in internal_utils.get_path_list("ONTOLOGY"):
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
        data = nfx.read(path)
        nid = data.get("nid", "")
        name = data.get("name", path.stem)
        version = data.get("version", "")
        dep_nids = []
        for dep in data.get("dependencies", []):
            dep_nid, _, _ = dep.partition("@")
            dep_nids.append(dep_nid)
        packages[nid] = {"name": name, "version": version, "dep_nids": dep_nids}

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
    with NeuroBase() as nb:
        nb.ontology.clear()


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, o="", strict=False):
    """Validate ontologies against the metaontology. -o: target file, --strict: also validate instances."""
    neurobase.clear(c, confirmed=True)
    ontology_dirs = internal_utils.get_path_list("ONTOLOGY")
    idx = OntologyIndex(*ontology_dirs)
    metaontology_nid = nfx.read(idx.metaontology_path).get("nid", "")
    targets = idx.all_targets(exclude_nid=metaontology_nid) if not o else _resolve_target(idx, o)

    failed = []
    with NeuroBase() as nb:
        for path in targets:
            nb.clear(confirm=True)
            nb.metaontology.import_nfx(path, index=idx)
            name = nfx.read(path).get("name", path.stem)
            valid = nb.metaontology.is_ontology_valid()
            if strict:
                valid = _validate_instances(nb, path) and valid
            dep_errors = idx.check_dependency_versions(path)
            if dep_errors:
                valid = False
            if valid:
                print(f"{terminal_style.SUCCESS} {name}")
            else:
                print(f"{terminal_style.FAIL} {name}")
                for v in nb.metaontology.violations:
                    print(f"  {v}")
                for err in dep_errors:
                    print(f"  {err}")
                failed.append(name)
            for w in nb.metaontology.violations.warnings:
                print(f"  {w}")

    if failed:
        raise SystemExit(1)
