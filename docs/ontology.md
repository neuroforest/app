# Ontology

The ontology module (`neuro.base.ontology`) defines the schema system for NeuroBase. It controls what node types exist, what properties they can have, and how nodes are validated before insertion.

## Graph Structure

The ontology is stored in Neo4j as a graph of its own, using three node types and five relationship types.

**Node types:**

- `OntologyNode` — defines a class/type (e.g. `Tiddler`, `Species`)
- `OntologyProperty` — defines a property (e.g. `created`, `nid`)
- `OntologyRelationship` — defines a relationship type (e.g. `HAS_PROPERTY`)

**Relationships:**

```
(OntologyNode)-[:SUBCLASS_OF]->(OntologyNode)
    Class hierarchy. Traversed with variable-length paths (*0..).

(OntologyNode)-[:HAS_PROPERTY]->(OntologyProperty)
    Optional property for a node type.

(OntologyNode)-[:REQUIRE_PROPERTY]->(OntologyProperty)
    Required property for a node type.

(OntologyNode)-[:HAS_RELATIONSHIP]->(OntologyRelationship)
    Declares a relationship type on a node.

(OntologyNode)-[:REQUIRE_RELATIONSHIP]->(OntologyRelationship)
    Subclass of HAS_RELATIONSHIP. The source node is required to emit at
    least one such relationship; absence is flagged at validate time.

(OntologyRelationship)-[:HAS_TARGET]->(OntologyNode)
    Specifies the target node type for a relationship.

(OntologyRelationship)-[:REQUIRE_TARGET]->(OntologyNode)
    Subclass of HAS_TARGET. The target node is required to receive at
    least one such relationship; absence is flagged at validate time
    (analogous to a SHACL inverse-path minCount 1, or an ER weak entity).
```

The required-edge subclasses are checked direction-aware: `REQUIRE_RELATIONSHIP` flags a missing *outgoing* edge on source instances; `REQUIRE_TARGET` flags a missing *incoming* edge on target instances. Both inherit through `SUBCLASS_OF*0..` on their respective node ends.

Properties are inherited through `SUBCLASS_OF` chains. If `Species` is a subclass of `Tiddler`, it inherits all of `Tiddler`'s required and optional properties.

## Classes

### Data classes (no database access)

**`Metaproperty`** — Represents a single property constraint for a node type. Holds the property label, owning node, property type (`DateTime`, `OntologyProperty`), and relationship type (`HAS_PROPERTY` or `REQUIRE_PROPERTY`). The `check()` method validates a value against the property type.

**`Metaproperties`** — A dict-like collection (`UserDict`) of `Metaproperty` objects keyed by property label. Ignores duplicate insertions. The `validate_properties()` method checks a node's properties against the collection, returning a `Violations` object with missing, undefined, and invalid properties.

**`Violations`** — Collects ontology violations found during validation. Truthy when violations exist, falsy when empty (no violations). Contains four lists:

- `undefined_labels` — labels not found as `OntologyNode` in the graph
- `missing_properties` — required properties (`REQUIRE_PROPERTY`) that are absent
- `missing_relationships` — required relationships absent: outgoing edges flagged via `REQUIRE_RELATIONSHIP`, incoming edges via `REQUIRE_TARGET`
- `undefined_properties` — properties present on the node but not defined in the ontology
- `invalid_properties` — properties with values that fail type checks

Supports two modes via `strict` flag:

- **strict** (default): all four lists count as violations
- **lenient**: `undefined_properties` are ignored (only missing, invalid, and undefined labels count)

Supports `+` operator to merge results across multiple labels.

### Database-aware classes (require a `NeuroBase` instance)

**`Ontology`** — Accessor mounted on `NeuroBase` as `nb.ontology`. Provides:

- `is_valid_node(node)` — validates a node's labels and properties against the ontology, returns a `Violations` object
- `info(label)` — returns an `OntologyNodeInfo` for the given label

**`OntologyNodeInfo`** — Queries and displays the full ontology profile for a node label: its lineage (`SUBCLASS_OF` chain), metaproperties (inherited through lineage), and relationships.

**`Validator`** — Base class for ontology validation. Provides `get_metaproperties(node_label)` which queries the ontology graph to resolve all properties (including inherited ones) for a given label.

**`ObjectValidator`** — Validates a `neuro.core.Object` against the ontology. A node may carry several class labels and is an instance of every one, so validation sees them **all at once**, against the union of their schemas (PLAN-2026-368). Runs three checks:

1. `validate_labels()` — verifies each label exists as an `OntologyNode`
2. `validate_label_antichain()` — the label set must be mutually incomparable: a label that is an ancestor or descendant of another is redundant (the subclass already implies its ancestors) and is reported in `redundant_labels`. No declared joining class is required.
3. `validate_properties()` / `validate_relationships()` — checks against the **union** over all valid labels, built by `MetapropertiesUnion.from_ontology` / `Metarelationships.union`. A property is undefined only if *no* label declares it; its value must satisfy *every* declaration (conjunction — two classes declaring it with incompatible types make every value invalid, and the message names both); the required set and the relationship set are the union across labels.

Returns a `Violations` object.

**`OntologyValidator`**, **`MetaontologyValidator`** — Placeholder validators for validating the ontology structure itself. Not yet implemented.

## Validation Flow

```
Object(labels, properties)
    │
    ▼
ObjectValidator.validate()
    │
    ├── validate_labels()
    │       For each label:
    │           MATCH (n:OntologyNode {label: $label})
    │           → undefined_labels if not found
    │
    ├── validate_label_antichain()
    │       Any two labels in SUBCLASS_OF* relation
    │           → redundant_labels (the subclass already implies the other)
    │
    └── validate_properties()
            Over the union of all valid labels:
                MetapropertiesUnion.from_ontology(labels)
                    → each label's declarations, kept per label
                union.validate_properties(object.properties)
                    → missing_properties (required by any label, absent)
                    → undefined_properties (declared by no label)
                    → invalid_properties (fails any declaration; conjunction)
                        │
                        ▼
                    Violations
```

## Usage

```python
from neuro.base import NeuroBase

with NeuroBase() as nb:
    # Inspect ontology for a label
    nb.ontology.info("Species").display()

    # Validate a node before insertion
    violations = nb.ontology.is_valid_node(node)
    if violations:
        print(violations)  # shows undefined labels, missing/invalid properties
```

`nb.nodes.put(node)` calls `is_valid_node` automatically and raises `ValueError` if violations are found.
