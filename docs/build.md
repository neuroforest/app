# build.py

Build NeuroForest app by copying custom editions into the TiddlyWiki tree.

    python bin/build.py

## Stages

### Copy editions

Copies validated edition directories from `tw5-editions/` into `tw5/editions/`. This makes custom editions available to TiddlyWiki for local testing and building.

If an edition already exists in the target, it is replaced.

### Validation

Each edition directory must contain a `tiddlywiki.info` file with valid JSON and the following required fields:

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Edition description |
| `plugins` | array | List of plugin references |
| `themes` | array | List of theme references |
| `build` | object | Build targets and their commands |

Editions that fail validation are skipped with a message explaining why:

- Missing `tiddlywiki.info` file
- Invalid JSON
- Missing required fields

Non-directory files (e.g. `README.md`) in `tw5-editions/` are silently ignored.

### Example edition

```
tw5-editions/
  neuro-neo4j/
    tiddlywiki.info
    tiddlers/
      ...
```

```json
{
    "description": "NeuroForest Neo4j edition",
    "plugins": ["neuroforest/core", "neuroforest/neo4j-syncadaptor"],
    "themes": ["neuroforest/basic"],
    "build": {
        "index": ["--rendertiddler", "$:/core/save/all", "index.html", "text/plain"]
    }
}
```

## Tests

    pytest tests/test_build.py
