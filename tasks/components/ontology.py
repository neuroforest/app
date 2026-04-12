import json
import os
from pathlib import Path

import invoke

from neuro.base import NeuroBase, nfx
from neuro.base.ontology import ObjectValidator
from neuro.utils import internal_utils, terminal_components, terminal_style
from tasks.actions import setup
from tasks.components import neurobase


def _metaontology_path():
    """Metaontology is always loaded from assets — it must stay in sync with the code."""
    return internal_utils.get_path("assets") / "ontology" / "metaontology.nfx"


def _build_registry(*dirs):
    meta_path = _metaontology_path()
    registry = {}
    # Pin metaontology to the canonical path.
    data = nfx.read(meta_path)
    for key in (data.get("nid", ""), data.get("name", ""), meta_path.stem, meta_path.name):
        if key:
            registry[key] = meta_path
    for d in dirs:
        for root, _, files in os.walk(d, followlinks=True):
            for fname in files:
                if not fname.endswith(".nfx"):
                    continue
                path = Path(root) / fname
                data = nfx.read(path)
                nid = data.get("nid", "")
                if nid:
                    registry.setdefault(nid, path)
                name = data.get("name", "")
                if name:
                    registry.setdefault(name, path)
                registry.setdefault(path.stem, path)
                registry.setdefault(path.name, path)
    return registry


def _resolve_targets(ontology_dirs, ontology, exclude_nid=None):
    if ontology:
        p = Path(ontology)
        extra_dirs = [p.parent] if p.exists() else []
        registry = _build_registry(*ontology_dirs, *extra_dirs)
        path = p if p.exists() else registry.get(ontology)
        if not path:
            print(f"{terminal_style.FAIL} Ontology not found: {ontology}")
            raise SystemExit(1)
        return registry, [path]
    else:
        registry = _build_registry(*ontology_dirs)
        targets = sorted(
            p for p in registry.values()
            if not exclude_nid or nfx.read(p).get("nid") != exclude_nid
        )
        # Deduplicate (registry maps multiple keys to the same path)
        seen = set()
        targets = [p for p in targets if str(p) not in seen and not seen.add(str(p))]
        return registry, targets


def _check_dependency_versions(path, registry):
    """Check that all dependencies have exact version match. Returns list of error strings."""
    data = nfx.read(path)
    errors = []
    for dep in data.get("dependencies", []):
        dep_nid, _, required_version = dep.partition("@")
        dep_path = registry.get(dep_nid)
        if not dep_path:
            errors.append(f"dependency {dep_nid} not found in registry")
            continue
        if not required_version:
            continue
        dep_data = nfx.read(dep_path)
        actual_version = dep_data.get("version", "")
        if actual_version != required_version:
            dep_name = dep_data.get("name", dep_path.stem)
            errors.append(f"{dep_name} requires {required_version}, found {actual_version}")
    return errors


def _load_with_deps(nb, path, registry, loaded=None):
    if loaded is None:
        loaded = set()
    if str(path) in loaded:
        return
    data = nfx.read(path)
    for dep in data.get("dependencies", []):
        dep_nid = dep.split("@")[0]
        dep_path = registry.get(dep_nid)
        if dep_path:
            _load_with_deps(nb, dep_path, registry, loaded)
    nb.metaontology.import_nfx(path)
    loaded.add(str(path))


@invoke.task(name="import", pre=[setup.env])
def import_(c, ontology=""):
    """Import ontology into neurobase."""
    ontology_dirs = internal_utils.get_path_list("ONTOLOGY")

    registry, targets = _resolve_targets(ontology_dirs, ontology)
    with NeuroBase() as nb:
        for path in targets:
            with terminal_style.step(path.stem):
                _load_with_deps(nb, path, registry)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def render(c, ontology=""):
    """Load ontology into neurobase and print Neo4j browser link."""
    neurobase.start(c)
    ontology_dirs = internal_utils.get_path_list("ONTOLOGY")

    registry, targets = _resolve_targets(ontology_dirs, ontology)
    with NeuroBase() as nb:
        nb.clear(confirm=True)

        for path in targets:
            with terminal_style.step(path.stem):
                _load_with_deps(nb, path, registry)

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
def registry(c):
    """Show discovered ontologies from ONTOLOGY search path."""
    app_dir = Path(os.environ["APP_DIR"])
    ontology_dirs = internal_utils.get_path_list("ONTOLOGY")
    reg = _build_registry(*ontology_dirs)
    seen = set()
    rows = []
    for path in reg.values():
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
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
    metaontology_nid = nfx.read(_metaontology_path()).get("nid", "")
    registry, targets = _resolve_targets(ontology_dirs, o, exclude_nid=metaontology_nid)

    failed = []
    with NeuroBase() as nb:
        for path in targets:
            nb.clear(confirm=True)
            _load_with_deps(nb, path, registry)
            name = nfx.read(path).get("name", path.stem)
            valid = nb.metaontology.is_ontology_valid()
            if strict:
                valid = _validate_instances(nb, path) and valid
            dep_errors = _check_dependency_versions(path, registry)
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