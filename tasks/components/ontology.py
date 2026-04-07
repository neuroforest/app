import os
from pathlib import Path

import invoke

from neuro.base import NeuroBase, nfx
from neuro.base.ontology import ObjectValidator
from neuro.base.schema import ONTOLOGY_OBJECTS
from neuro.utils import internal_utils, terminal_style
from tasks.actions import setup
from tasks.components import neurobase


def _build_registry(*dirs):
    registry = {}
    for d in dirs:
        for path in Path(d).glob("*.nfx"):
            data = nfx.read(path)
            nid = data.get("nid", "")
            if nid:
                registry[nid] = path
            name = data.get("name", "")
            if name:
                registry[name] = path
            registry[path.stem] = path
            registry[path.name] = path
    return registry


def _resolve_targets(ontology_dir, ontology, exclude_nid=None):
    if ontology:
        p = Path(ontology)
        extra_dir = p.parent if p.exists() else None
        registry = _build_registry(ontology_dir, *([extra_dir] if extra_dir else []))
        path = p if p.exists() else registry.get(ontology)
        if not path:
            print(f"{terminal_style.FAIL} Ontology not found: {ontology}")
            raise SystemExit(1)
        return registry, [path]
    else:
        registry = _build_registry(ontology_dir)
        targets = sorted(
            p for p in ontology_dir.glob("*.nfx")
            if not exclude_nid or nfx.read(p).get("nid") != exclude_nid
        )
        return registry, targets


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


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def render(c, ontology=""):
    """Load ontology into neurobase and print Neo4j browser link."""
    neurobase.start(c)
    ontology_dir = internal_utils.get_path("assets") / "ontology"

    registry, targets = _resolve_targets(ontology_dir, ontology)
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
    ontology_labels = set(ONTOLOGY_OBJECTS)
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


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, o="", strict=False):
    """Validate ontologies against the metaontology. -o: target file, --strict: also validate instances."""
    neurobase.reset(c, confirmed=True)
    ontology_dir = internal_utils.get_path("assets") / "ontology"
    metaontology_nid = nfx.read(ontology_dir / "metaontology.nfx").get("nid", "")
    registry, targets = _resolve_targets(ontology_dir, o, exclude_nid=metaontology_nid)

    failed = []
    with NeuroBase() as nb:
        for path in targets:
            nb.clear(confirm=True)
            _load_with_deps(nb, path, registry)
            name = nfx.read(path).get("name", path.stem)
            valid = nb.metaontology.is_ontology_valid()
            if strict:
                valid = _validate_instances(nb, path) and valid
            if valid:
                print(f"{terminal_style.SUCCESS} {name}")
            else:
                print(f"{terminal_style.FAIL} {name}")
                if nb.metaontology.violations:
                    print(repr(nb.metaontology.violations))
                failed.append(name)

    if failed:
        raise SystemExit(1)