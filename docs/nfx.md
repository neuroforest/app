# NFX – NeuroForest Exchange

Graph interchange format for nodes and relationships.

- Extension: `.nfx`
- MIME: `application/nfx+json`

## Structure

```json
{
  "nid": "<uuid-v4>",
  "name": "Namespace/Name",
  "description": "Optional description",
  "version": "1.0",
  "dependencies": ["<nid>@1.0"],
  "nodes": [
    {
      "nid": "<uuid-v4>",
      "labels": ["Label1", "Label2"],
      "properties": {
        "title": "Example",
        "neuro.role": "taxon.species"
      }
    }
  ],
  "relationships": [
    {
      "to": "<nid>",
      "from": "<nid>",
      "type": "PARENT_OF",
      "properties": {"weight": 1}
    }
  ]
}
```

## Fields

### Top-level

| Field          | Type     | Required | Description                               |
|----------------|----------|----------|-------------------------------------------|
| `nid`          | `string` | yes      | Stable UUID v4 identity of this ontology  |
| `name`         | `string` | no       | Human-readable name (e.g. `Metaontology`) |
| `description`  | `string` | no       | Human-readable description                |
| `version`      | `string` | no       | Version identifier (e.g. `"2.0"`)         |
| `dependencies` | `list`   | no       | Required ontologies: `<nid>@<version>`    |

### Node

| Field        | Type     | Description                                                  |
|--------------|----------|--------------------------------------------------------------|
| `nid`        | `string` | UUID v4 identifying the node (stored as `nid` in Neo4j) |
| `labels`     | `list`   | Neo4j labels (e.g. `["Tiddler"]`)                            |
| `properties` | `dict`   | Node properties (excludes `nid`). Omitted when empty.   |

### Relationship

| Field        | Type     | Description                                  |
|--------------|----------|----------------------------------------------|
| `to`         | `string` | `nid` of the target node                     |
| `from`       | `string` | `nid` of the source node                     |
| `type`       | `string` | Relationship type (e.g. `"PARENT_OF"`)       |
| `properties` | `dict`   | Relationship properties. Omitted when empty. |

## API

### Export

`type` and `nid` are required on the generic exporter: it exports an arbitrary
query result, so there is no metadata node to read a header off, and a `nid` is
never minted for you. Every exporter validates before writing and raises rather
than producing a document the pre-commit lint would reject.

```python
# Export nodes filtered by label and/or properties
nb.nodes.export_nfx(path, type="knowledge", nid=uuid4, label="Tiddler",
                    name="my-export", version="1.0")

# Export nodes by custom Cypher (must return nid, labels, properties columns)
nb.nodes.export_nfx(path, type="knowledge", nid=uuid4, name="taxa", version="1.0", query="""
    MATCH (n:Taxon)
    WHERE n.`nid` IS NOT NULL
    RETURN n.`nid` as nid, labels(n) as labels, properties(n) as properties
""")

# Export one ontology as a module file, header read off its OntologyMetadata
nb.ontology.export_nfx(path, name="Filesystem")

# Export every ontology in the base — `path` is a directory, one <name>.nfx each
nb.ontology.export_nfx(directory)

# Export the metaontology (schema definition)
nb.metaontology.export_nfx(path)
```

`export_nfx` writes matched nodes and their inter-node relationships to the file. `nid` is extracted to the `nid` field and removed from `properties`.

An ontology export is scoped by what its `OntologyMetadata` node `DEFINES`. A
relationship goes to the module that may legally declare it — one endpoint its
own, the other reachable through its dependencies — so a cross-module edge lands
in the dependent, not in the dependency whose node happens to be the source.

Two things an ontology export cannot recover, both because the graph does not
hold them: `hash` (run `nde ontology.rehash` afterwards for a dir-form plugin),
and the *pinned* dependency versions — the emitted pins are each dependency's
current version in that base. The export is faithful to the base, not to the
file history.

### Import

```python
# Import nodes with ontology validation
nb.nodes.import_nfx(path)

# Import metaontology (bypasses validation — schema defines validation rules)
nb.metaontology.import_nfx(path)
```

Reads the file and merges on `nid`. Relationships are merged between the referenced nodes. Existing data is updated, not duplicated. Also creates/updates an `OntologyMetadata` node from the top-level fields and wires `DEPENDS_ON` edges to declared dependencies.

## Low-level I/O

The `neuro.base.nfx` module provides pure read/write/validate helpers over the `Nfx` value object. No database dependency.

```python
from neuro.base import nfx
from neuro.base.nfx import Nfx

doc = nfx.read(path)              # → Nfx (frozen dataclass)
doc.nid, doc.name, doc.version    # attribute access; "" when absent
doc.dependencies                  # tuple of (nid, version) pairs
doc.dep_nids, doc.node_nids       # convenience projections

nfx.write(path, doc)              # serialize Nfx to canonical text
nfx.dumps(doc)                    # same, returning str

# Construct from dict (raises NfxViolation on malformed nid / dep "nid@ver"):
Nfx.from_dict({"nid": "...", "nodes": [...], "relationships": [...]})
doc.to_dict()                     # round-trips to canonical dict

# Validate referential integrity (unresolved/foreign rels, invalid nids):
report = nfx.validate(doc, dependency_nids=...)

# Walk the dep DAG (returns nids of all transitively-reachable dep nodes):
nids = nfx.dependency_node_nids(doc, resolve=lambda nid: Nfx | None)

# Format-level lint on the *raw* dict (key order, unknown keys); use before
# parse since `Nfx` discards unknowns:
lint = nfx.lint_format(json.loads(path.read_text()))
```

`Nfx` is frozen; mutate via `dataclasses.replace(doc, version="1.4")`.
