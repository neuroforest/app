import json
import logging
import os
import subprocess
import sys
import time

import invoke
import neo4j

from neuro.base.api import NeuroBase
from neuro.base.index import OntologyIndex
from neuro.base.schema import Metaproperties, Metarelationships, Violations
from neuro.utils import docker_tools
from neuro.utils import build_utils, internal_utils, network_utils, terminal_components, terminal_style

from tasks.actions import setup


def _forbidden_labels():
    raw = os.getenv("FORBIDDEN_KNOWLEDGE", "").strip()
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def _meta_labels():
    oo = json.loads(os.environ["ONTOLOGY_OBJECTS"])
    return frozenset(oo) | {"Metaontology"}


def _reject_if_forbidden(label):
    if label in _forbidden_labels():
        print(f"{terminal_style.FAIL} Forbidden type: {label}", file=sys.stderr)
        raise SystemExit(1)


def _knowledge_labels(nb):
    oo = json.loads(os.environ["ONTOLOGY_OBJECTS"])
    query = """
    MATCH (on:OntologyNode)
    WHERE NOT on:Metaontology
      AND NOT on.label IN $oo
      AND NOT EXISTS {
        MATCH (on)-[:SUBCLASS_OF*]->(p:OntologyNode)
        WHERE p.label IN $oo
      }
    RETURN DISTINCT on.label AS label
    ORDER BY label
    """
    return [r["label"] for r in nb.get_data(query, {"oo": oo})]


def _data_type_labels(nb):
    query = """
    MATCH (on:OntologyNode)-[:SUBCLASS_OF*1..]->(:OntologyNode {label: 'OntologyProperty'})
    RETURN DISTINCT on.label AS label
    ORDER BY label
    """
    return [r["label"] for r in nb.get_data(query)]


def _count_rel_type(nb, rel_type):
    return nb.get_data(f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS c")[0]["c"]


def _knowledge_rel_types(nb):
    oo = json.loads(os.environ["ONTOLOGY_OBJECTS"])
    query = """
    MATCH (o:OntologyRelationship)
    WHERE NOT o:Metaontology
      AND NOT o.label IN $oo
      AND NOT EXISTS {
        MATCH (o)-[:SUBCLASS_OF*]->(p:OntologyRelationship)
        WHERE p.label IN $oo
      }
    RETURN DISTINCT o.label AS rel_type
    ORDER BY rel_type
    """
    return [r["rel_type"] for r in nb.get_data(query, {"oo": oo})]


def _present_labels(nb):
    data = nb.get_data("CALL db.labels() YIELD label RETURN label")
    return {r["label"] for r in data}


def _present_rel_types(nb):
    data = nb.get_data("CALL db.relationshipTypes() YIELD relationshipType AS t RETURN t")
    return {r["t"] for r in data}


def _fmt_value(v, max_len=120):
    s = repr(v)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _count_label(nb, label):
    return nb.get_data(f"MATCH (n:`{label}`) RETURN count(n) AS count")[0]["count"]


def _sample_props(nb, label, size):
    query = f"MATCH (n:`{label}`) RETURN properties(n) AS props LIMIT $size"
    return [r["props"] for r in nb.get_data(query, {"size": size})]


def _rel_summary(nb, label, forbidden):
    forbidden_list = list(forbidden)
    out_query = f"""
    MATCH (n:`{label}`)-[r]->(b)
    WHERE NONE(lb IN labels(b) WHERE lb IN $forbidden)
    WITH type(r) AS rel, [lb IN labels(b) WHERE NOT lb IN $forbidden] AS lbs, count(*) AS cnt
    RETURN rel, lbs, cnt
    ORDER BY cnt DESC
    LIMIT 10
    """
    in_query = f"""
    MATCH (a)-[r]->(n:`{label}`)
    WHERE NONE(lb IN labels(a) WHERE lb IN $forbidden)
      AND NOT $label IN labels(a)
    WITH type(r) AS rel, [lb IN labels(a) WHERE NOT lb IN $forbidden] AS lbs, count(*) AS cnt
    RETURN rel, lbs, cnt
    ORDER BY cnt DESC
    LIMIT 10
    """
    return {
        "out": nb.get_data(out_query, {"forbidden": forbidden_list, "label": label}),
        "in": nb.get_data(in_query, {"forbidden": forbidden_list, "label": label}),
    }


def verify_neo4j(timeout=32):
    logging.getLogger("neo4j").setLevel(logging.ERROR)
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    deadline = time.monotonic() + timeout
    while True:
        driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
        try:
            driver.verify_connectivity()
            return
        except (neo4j.exceptions.ServiceUnavailable, Exception):
            if time.monotonic() >= deadline:
                print(f"Neo4j inaccessible: {uri}")
                base_name = os.getenv("BASE_NAME")
                logs = subprocess.run(
                    ["docker", "logs", "--tail", "50", base_name],
                    capture_output=True, text=True,
                )
                print(logs.stdout)
                print(logs.stderr)
                sys.exit(1)
            time.sleep(0.5)
        finally:
            driver.close()


@invoke.task(pre=[setup.env])
def create(c):
    """Create the neurobase docker container if it doesn't exist."""
    base_name = os.getenv("BASE_NAME")

    if docker_tools.container_exists(base_name):
        return

    with terminal_components.step(f"Compose NeuroBase: {base_name}"):
        result = subprocess.run(["docker", "compose", "up", "-d"], capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr)
            raise SystemExit(1)


@invoke.task(pre=[setup.env])
def start(c):
    """Start the neurobase docker container and wait for Neo4j."""
    docker_tools.verify_access()
    base_name = os.getenv("BASE_NAME")
    create(c)
    bolt_port = int(os.getenv("NEO4J_PORT_BOLT", 7687))

    if not docker_tools.container_exists(base_name):
        print(f"{terminal_style.FAIL} NeuroBase container does not exist: {base_name}")
        raise SystemExit(1)

    with terminal_components.step(f"Start NeuroBase instance: {base_name}"):
        if not docker_tools.container_running(base_name):
            subprocess.run(["docker", "start", base_name], capture_output=build_utils.quiet())
        network_utils.wait_for_socket("127.0.0.1", bolt_port, timeout=32)
        verify_neo4j()


@invoke.task(pre=[setup.env])
def count(c):
    """Print the number of nodes in the neurobase."""
    with NeuroBase() as nb:
        print(nb.count())


@invoke.task(pre=[setup.env])
def clear(c, confirmed=False):
    """Clear all data from the test database after confirmation."""
    base_name = os.getenv("BASE_NAME")
    start(c)
    with NeuroBase() as nb:
        node_count = nb.count()
        if node_count == 0:
            return
        if not confirmed:
            if not terminal_components.bool_prompt(f"Clear '{base_name}'? ({node_count} nodes will be deleted)"):
                raise SystemExit("Aborting clear.")
        with terminal_components.step(f"Clear test database: {base_name}"):
            nb.clear(confirm=True)


@invoke.task(pre=[setup.env])
def stop(c):
    """Stop the neurobase docker container."""
    base_name = os.getenv("BASE_NAME")

    if not docker_tools.container_running(base_name):
        print(f"{terminal_style.SUCCESS} Already stopped: {base_name}")
        return

    with terminal_components.step(f"Stop NeuroBase instance: {base_name}"):
        subprocess.run(["docker", "stop", base_name], capture_output=build_utils.quiet())


@invoke.task(pre=[setup.env])
def backup(c):
    """Backup the neurobase docker container and clean up temporary artifacts."""
    base_name = os.getenv("BASE_NAME")
    stop(c)

    container = docker_tools.Container(name=base_name)
    with terminal_components.step(f"Backup '{base_name}' to {internal_utils.get_path('archive')}"):
        container.backup()
        container.clean()


@invoke.task(pre=[setup.env])
def restore(c, backup=None):
    """Restore the neurobase container from a backup."""
    base_name = os.getenv("BASE_NAME")
    container = docker_tools.Container(name=base_name)

    if not backup:
        archive_dir = internal_utils.get_path("archive") / "base"
        backups = [
            b for b in sorted(str(p) for p in __import__("pathlib").Path(archive_dir).iterdir())
            if docker_tools.Container.is_valid_backup(b) and base_name in b.rsplit("/", 1)[1]
        ]
        if not backups:
            print(f"{terminal_style.FAIL} No backups found for '{base_name}'")
            raise SystemExit(1)
        backup = terminal_components.selector([b.rsplit("/", 1)[1] for b in backups])
        if not backup:
            raise SystemExit("Aborting restore.")

    # Resolve backup path
    if not docker_tools.Container.is_valid_backup(backup):
        backup = str(internal_utils.get_path("archive") / "base" / backup)
    if not docker_tools.Container.is_valid_backup(backup):
        print(f"{terminal_style.FAIL} Invalid backup: {backup}")
        raise SystemExit(1)
    container.backup_location = backup

    stop(c)

    data_volume = f"{base_name}-data"
    with terminal_components.step(f"Restore data: {base_name}"):
        container.restore_data(data_volume)

    start(c)


@invoke.task(pre=[setup.env])
def query(c, cypher):
    """Run a Cypher query against the neurobase and print results."""
    start(c)
    with NeuroBase() as nb:
        records = nb.get_data(cypher)
        for record in records:
            print(record)


@invoke.task(pre=[setup.env])
def delete(c):
    """Remove the neurobase container and its associated volumes."""
    base_name = os.getenv("BASE_NAME")
    stop(c)

    if not docker_tools.container_exists(base_name):
        print(f"{terminal_style.FAIL} NeuroBase '{base_name}' not found")
        return

    if not terminal_components.bool_prompt(f"Delete '{base_name}' and its volumes?", default=True):
        raise SystemExit("Aborting delete.")

    volumes = docker_tools.get_container_volumes(base_name)

    with terminal_components.step(f"Remove container: {base_name}"):
        subprocess.run(["docker", "rm", base_name], capture_output=build_utils.quiet())

    for vol in volumes:
        with terminal_components.step(f"Remove volume: {vol}"):
            subprocess.run(["docker", "volume", "rm", vol], capture_output=build_utils.quiet())


@invoke.task(pre=[setup.env])
def overview(c, fmt="text"):
    """Summarize the neurobase: types, data types, relations, with counts."""
    forbidden = _forbidden_labels()
    meta = _meta_labels()
    result = {}
    with NeuroBase() as nb:
        present = _present_labels(nb)
        knowledge = set(_knowledge_labels(nb))
        data_types = set(_data_type_labels(nb))

        types = sorted((present & knowledge) - forbidden)
        empty = sorted(knowledge - present - forbidden)
        data = sorted((present & data_types) - forbidden)
        orphans = sorted(present - knowledge - data_types - forbidden - meta)

        type_counts = {lb: _count_label(nb, lb) for lb in types}

        rel_present = _present_rel_types(nb)
        rel_knowledge = set(_knowledge_rel_types(nb))
        relations = sorted(rel_present & rel_knowledge)
        rel_counts = {r: _count_rel_type(nb, r) for r in relations}

        result = {
            "types": [{"label": lb, "count": type_counts[lb]} for lb in types],
            "empty": empty,
            "data_types": data,
            "orphans": orphans,
            "relations": [{"type": r, "count": rel_counts[r]} for r in relations],
        }

    if fmt == "json":
        print(json.dumps(result, indent=2))
        return

    B, RST, DIM = terminal_style.BOLD, terminal_style.RESET, terminal_style.DIM
    total_nodes = sum(type_counts.values())
    total_edges = sum(rel_counts.values())
    print(
        f"{DIM}{len(types)} types · {total_nodes} nodes · "
        f"{len(relations)} relations · {total_edges} edges{RST}"
    )

    if types:
        print(f"\n{B}Types{RST}")
        w = max(len(lb) for lb in types)
        for lb in types:
            print(f"  {lb:<{w}}  {type_counts[lb]}")

    if empty:
        print(f"\n{B}Empty{RST} ({len(empty)}): {', '.join(empty)}")
    if data:
        print(f"{B}Data types{RST} ({len(data)}): {', '.join(data)}")
    if orphans:
        print(f"{B}Orphans{RST} ({len(orphans)}): {', '.join(orphans)}")

    if relations:
        print(f"\n{B}Relations{RST}")
        w = max(len(r) for r in relations)
        for r in relations:
            print(f"  {r:<{w}}  {rel_counts[r]}")


def _iter_nodes_for_validation(nb, label, size, all_mode, batch=1000):
    """Yield {"props", "nid"} rows for validation. Streams in batches when all_mode."""
    if all_mode:
        skip = 0
        while True:
            rows = nb.get_data(
                f"MATCH (n:`{label}`) "
                f"RETURN properties(n) AS props, n.`neuro.id` AS nid "
                f"ORDER BY n.`neuro.id` SKIP {skip} LIMIT {batch}"
            )
            if not rows:
                return
            yield from rows
            if len(rows) < batch:
                return
            skip += batch
    else:
        rows = nb.get_data(
            f"MATCH (n:`{label}`) "
            f"RETURN properties(n) AS props, n.`neuro.id` AS nid "
            f"LIMIT {size}"
        )
        yield from rows


def _node_id(nid, props):
    return (
        nid
        or props.get("neuro.id")
        or props.get("uuid")
        or props.get("title")
        or props.get("id")
        or "?"
    )


def _aggregate_violations(pairs):
    agg = {
        "missing_properties": {},
        "undefined_properties": {},
        "invalid_properties": {},
        "undefined_relationships": {},
        "missing_relationships": {},
        "invalid_relationships": {},
        "warnings": {},
    }
    for nid, v in pairs:
        for p in v.missing_properties:
            agg["missing_properties"].setdefault(p.label, []).append(nid)
        for k in v.undefined_properties:
            agg["undefined_properties"].setdefault(k, []).append(nid)
        for k, reason in v.invalid_properties:
            agg["invalid_properties"].setdefault(f"{k} ({reason})", []).append(nid)
        for rel, direction, _lbs in v.undefined_relationships:
            agg["undefined_relationships"].setdefault(f"{rel} ({direction})", []).append(nid)
        for mr in v.missing_relationships:
            agg["missing_relationships"].setdefault(mr.label, []).append(nid)
        for rel, direction, _actual, expected in v.invalid_relationships:
            agg["invalid_relationships"].setdefault(
                f"{rel} ({direction}, expected {expected})", []
            ).append(nid)
        for w in v.warnings:
            agg["warnings"].setdefault(w, []).append(nid)
    return agg


def _print_validation_entry(entry, all_mode, example_cap=5):
    B, RST, DIM = terminal_style.BOLD, terminal_style.RESET, terminal_style.DIM
    warn_part = f", {entry['warn']} warn" if entry.get("warn") else ""
    header = (
        f"{B}{entry['label']}{RST} "
        f"{DIM}({entry['count']:,} nodes — "
        f"{entry['pass']} pass, {entry['fail']} fail{warn_part}){RST}"
    )
    print(f"\n{header}")

    if all_mode:
        agg = entry["violations"]
        kinds = (
            ("missing", "missing_properties"),
            ("undefined", "undefined_properties"),
            ("invalid", "invalid_properties"),
            ("undefined rel", "undefined_relationships"),
            ("missing rel", "missing_relationships"),
            ("invalid rel", "invalid_relationships"),
            ("warn", "warnings"),
        )
        for tag, key in kinds:
            for k, nids in sorted(agg[key].items()):
                ex = ", ".join(str(n) for n in nids[:example_cap])
                more = "" if len(nids) <= example_cap else f", +{len(nids) - example_cap} more"
                print(f"  {tag} {B}{k}{RST} × {len(nids)}  {DIM}e.g. [{ex}{more}]{RST}")
        return

    for d in entry["details"]:
        tag = terminal_style.SUCCESS if d["ok"] else terminal_style.FAIL
        verdict = "PASS" if d["ok"] else "FAIL"
        print(f"  {tag} {verdict}  [{d['nid']}]")
        if d["missing"]:
            print(f"        missing: {d['missing']}")
        if d["undefined"]:
            print(f"        undefined: {d['undefined']}")
        for k, r in d["invalid"]:
            print(f"        invalid: {k} ({r})")
        for r, dr, lbs in d["undefined_rel"]:
            print(f"        undefined rel: {r} ({dr}, {lbs})")
        if d["missing_rel"]:
            print(f"        missing rel: {d['missing_rel']}")
        for r, dr, actual, expected in d["invalid_rel"]:
            print(f"        invalid rel: {r} ({dr}, expected {expected}, got {actual})")
        for w in d.get("warnings", []):
            print(f"        {terminal_style.YELLOW}{w}{terminal_style.RESET}")


def _detail_record(nid, v):
    return {
        "nid": nid,
        "ok": not v,
        "missing": [p.label for p in v.missing_properties],
        "undefined": list(v.undefined_properties),
        "invalid": list(v.invalid_properties),
        "undefined_rel": list(v.undefined_relationships),
        "missing_rel": [m.label for m in v.missing_relationships],
        "invalid_rel": list(v.invalid_relationships),
        "warnings": list(v.warnings),
    }


@invoke.task(pre=[setup.env])
def validate(c, type="", size=5, all=False, strict=False, fmt="text"):
    """Validate knowledge nodes against the ontology. --type: one type. --size: samples per type. --all: every node (expensive). --strict: treat unvalidated types as fail (default warns and falls back to String). Exits non-zero on violations."""
    OntologyIndex(*internal_utils.get_path_list("ONTOLOGY"))
    forbidden = _forbidden_labels()
    had_violations = False
    report = []

    with NeuroBase() as nb:
        if type:
            _reject_if_forbidden(type)
            present = _present_labels(nb)
            allowed = set(_knowledge_labels(nb))
            if type not in present:
                diagnosis = "No instances" if type in allowed else "Unknown type"
                print(f"{terminal_style.FAIL} {diagnosis}: {type}", file=sys.stderr)
                raise SystemExit(1)
            if type not in allowed:
                print(f"{terminal_style.WARN} Undefined type: {type}", file=sys.stderr)
            targets = [type]
        else:
            knowledge = set(_knowledge_labels(nb))
            present = _present_labels(nb)
            targets = sorted((knowledge & present) - forbidden)

        for lb in targets:
            try:
                metaprops = Metaproperties.from_ontology(nb, lb)
                metarels = Metarelationships.from_ontology(nb, lb)
            except Exception as e:
                print(f"{terminal_style.FAIL} {lb}: schema load failed ({e})", file=sys.stderr)
                had_violations = True
                continue

            count = _count_label(nb, lb)
            results = []
            for row in _iter_nodes_for_validation(nb, lb, size, all):
                v = Violations()
                metaprops.validate_properties(row["props"], v, strict=strict)
                if row.get("nid") and metarels:
                    metarels.validate_relationships(nb, row["nid"], v)
                results.append((_node_id(row.get("nid"), row["props"]), v))

            entry = {
                "label": lb,
                "count": count,
                "sampled": len(results),
                "pass": sum(1 for _, v in results if not v),
                "fail": sum(1 for _, v in results if v),
            }
            if all:
                entry["violations"] = _aggregate_violations([(n, v) for n, v in results if v or v.warnings])
            else:
                entry["details"] = [_detail_record(nid, v) for nid, v in results]
            entry["warn"] = sum(1 for _, v in results if v.warnings)

            if entry["fail"]:
                had_violations = True

            if fmt == "text":
                _print_validation_entry(entry, all)
            report.append(entry)

    if fmt == "json":
        print(json.dumps(report, indent=2, default=str))

    if had_violations:
        raise SystemExit(1)


@invoke.task(pre=[setup.env])
def sample(c, type="", size=3, rels=True, count=True, fmt="text"):
    """Sample knowledge nodes per type. --type: one type. --size: samples per type. --no-count/--no-rels: fast mode."""
    forbidden = _forbidden_labels()
    with NeuroBase() as nb:
        if type:
            _reject_if_forbidden(type)
            present = _present_labels(nb)
            allowed = set(_knowledge_labels(nb))
            if type not in present:
                diagnosis = "No instances" if type in allowed else "Unknown type"
                print(f"{terminal_style.FAIL} {diagnosis}: {type}", file=sys.stderr)
                raise SystemExit(1)
            if type not in allowed:
                print(f"{terminal_style.WARN} Undefined type: {type}", file=sys.stderr)
            targets = [type]
        else:
            knowledge = set(_knowledge_labels(nb))
            present = _present_labels(nb)
            targets = sorted((knowledge & present) - forbidden)

        report = []
        for lb in targets:
            entry = {"label": lb, "samples": _sample_props(nb, lb, size)}
            if count:
                entry["count"] = _count_label(nb, lb)
            if rels:
                entry["rels"] = _rel_summary(nb, lb, forbidden)
            report.append(entry)

    if fmt == "json":
        print(json.dumps(report, indent=2, default=str))
        return

    B, RST, DIM = terminal_style.BOLD, terminal_style.RESET, terminal_style.DIM
    id_keys = ("uuid", "neuro.id", "id")
    for entry in report:
        header = f"{B}{entry['label']}{RST}"
        if count:
            header += f" {DIM}({entry['count']}){RST}"
        print(f"\n{header}")
        for i, props in enumerate(entry["samples"], 1):
            ident = next((props[k] for k in id_keys if k in props), None)
            tag = f"{DIM}[{i}]{RST}"
            if ident is not None:
                print(f"  {tag} {ident}")
            else:
                print(f"  {tag}")
            for k in sorted(props):
                if k in id_keys:
                    continue
                print(f"      {k}: {_fmt_value(props[k])}")
            print()
        if rels and (entry["rels"]["out"] or entry["rels"]["in"]):
            print(f"  {DIM}relationships{RST}")
            for r in entry["rels"]["out"]:
                target = ":".join(r["lbs"]) or "?"
                print(f"    (:{entry['label']}) -[:{r['rel']}]-> (:{target}) × {r['cnt']}")
            for r in entry["rels"]["in"]:
                source = ":".join(r["lbs"]) or "?"
                print(f"    (:{source}) -[:{r['rel']}]-> (:{entry['label']}) × {r['cnt']}")
