# build_tw5.py

Build NeuroForest app by assembling custom editions and plugins into the TiddlyWiki tree.

    python bin/build_tw5.py

## Stages

### 1. Copy editions

Copies validated edition directories from `tw5-editions/` into `tw5/editions/`. This makes custom editions available to TiddlyWiki for local testing and building.

If an edition already exists in the target, it is replaced.

#### Edition validation

Each edition directory must contain a `tiddlywiki.info` file with valid JSON and the following required fields:

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Edition description |
| `plugins` | array | List of plugin references |
| `themes` | array | List of theme references |
| `build` | object | Build targets and their commands |

#### Example edition

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

### 2. Copy plugins

Discovers plugins and themes in `tw5-plugins/` by walking the directory tree for `plugin.info` files, then copies them into `tw5/plugins/` or `tw5/themes/` based on the `plugin-type` field.

#### Plugin discovery

The script walks `tw5-plugins/` recursively for `plugin.info` files. Two directory patterns are supported:

- **Neuroforest repos**: `tw5-plugins/neuroforest/<name>/source/plugin.info` — the `source/` directory is copied
- **Third-party**: `tw5-plugins/<author>/<name>/plugin.info` — the plugin directory is copied

#### Plugin validation

Each `plugin.info` must contain valid JSON with required fields:

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | TiddlyWiki title (e.g. `$:/plugins/acme/widget`) |
| `description` | string | Plugin description |

#### Segregation by type

The `plugin-type` field determines the target directory:

| `plugin-type` | Target | Example |
|---------------|--------|---------|
| `"plugin"` or not set | `tw5/plugins/<author>/<name>/` | `$:/plugins/kookma/shiraz` → `tw5/plugins/kookma/shiraz/` |
| `"theme"` | `tw5/themes/<author>/<name>/` | `$:/themes/neuroforest/basic` → `tw5/themes/neuroforest/basic/` |

The `<author>/<name>` path is derived from the `title` field by stripping the `$:/plugins/` or `$:/themes/` prefix.

#### Example plugin

```
tw5-plugins/
  kookma/
    shiraz/
      plugin.info
      readme.tid
      styles.tid
      ...
```

```json
{
    "title": "$:/plugins/kookma/shiraz",
    "description": "extended markups, styles, images, tables, and macros",
    "plugin-type": "plugin",
    "version": "2.9.0"
}
```

## Tests

    pytest tests/test_build_tw5.py
