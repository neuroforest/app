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
| `nid`        | `string` | UUID v4 identifying the node (stored as `neuro.id` in Neo4j) |
| `labels`     | `list`   | Neo4j labels (e.g. `["Tiddler"]`)                            |
| `properties` | `dict`   | Node properties (excludes `neuro.id`). Omitted when empty.   |

### Relationship

| Field        | Type     | Description                                  |
|--------------|----------|----------------------------------------------|
| `to`         | `string` | `nid` of the target node                     |
| `from`       | `string` | `nid` of the source node                     |
| `type`       | `string` | Relationship type (e.g. `"PARENT_OF"`)       |
| `properties` | `dict`   | Relationship properties. Omitted when empty. |

## API

### Export

```python
# Export nodes filtered by label and/or properties
nb.nodes.export_nfx(path, label="Tiddler", name="My Export")

# Export nodes by custom Cypher (must return nid, labels, properties columns)
nb.nodes.export_nfx(path, query="""
    MATCH (n:Taxon)
    WHERE n.`neuro.id` IS NOT NULL
    RETURN n.`neuro.id` as nid, labels(n) as labels, properties(n) as properties
""")

# Export all ontology instances (all SUBCLASS_OF descendants of OntologyNode,
# OntologyRelationship, OntologyProperty)
nb.ontology.export_nfx(path)

# Export the metaontology (schema definition)
nb.metaontology.export_nfx(path)
```

`export_nfx` writes matched nodes and their inter-node relationships to the file. `neuro.id` is extracted to the `nid` field and removed from `properties`.

### Import

```python
# Import nodes with ontology validation
nb.nodes.import_nfx(path)

# Import metaontology (bypasses validation — schema defines validation rules)
nb.metaontology.import_nfx(path)
```

Reads the file and merges on `neuro.id`. Relationships are merged between the referenced nodes. Existing data is updated, not duplicated. Also creates/updates an `OntologyMetadata` node from the top-level fields and wires `DEPENDS_ON` edges to declared dependencies.

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
