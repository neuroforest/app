import json
import os
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
            with terminal_style.step(name) as status:
                def on_import(dep_name, imported):
                    status.log(f"  {'▸' if imported else '-'} {dep_name}{'' if imported else ' (loaded)'}")
                nb.metaontology.import_nfx(path, index=idx, on_import=on_import)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def render(c, ontology=""):
    """Load ontology into neurobase and print Neo4j browser link."""
    neurobase.start(c)
    ontology_dirs = internal_utils.get_path_list("ONTOLOGY")
    idx = OntologyIndex(*ontology_dirs)

    targets = _resolve_target(idx, ontology)
    with NeuroBase() as nb:
        nb.clear(confirm=True)

        for path in targets:
            name = nfx.read(path).get("name", path.stem)
            with terminal_style.step(name):
                nb.metaontology.import_nfx(path, index=idx)

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
def index(c):
    """Show discovered ontologies from ONTOLOGY search path."""
    app_dir = Path(os.environ["APP_DIR"])
    ontology_dirs = internal_utils.get_path_list("ONTOLOGY")
    idx = OntologyIndex(*ontology_dirs)
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


@invoke.task(pre=[setup.env])
def info(c, label):
    """Show ontology info for a label."""
    with NeuroBase() as nb:
        nb.ontology.info(label).display()


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
