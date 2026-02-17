# TW5

TiddlyWiki5 tree assembly: copy custom editions and plugins, then run TW5 tests.

## Tasks

| Task | Description |
|------|-------------|
| `tw5.bundle` | Copy editions and plugins into the TW5 tree |
| `tw5.test` | Bundle and run `tw5/bin/test.sh` |

## Bundle

    invoke tw5.bundle

### 1. Copy editions

Copies validated edition directories from `tw5-editions/` into `tw5/editions/`. If an edition already exists in the target, it is replaced.

#### Edition validation

Each edition directory must contain a `tiddlywiki.info` file with valid JSON and the required fields:

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Edition description |
| `plugins` | array | List of plugin references |
| `themes` | array | List of theme references |
| `build` | object | Build targets and their commands |

#### Example

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

Discovers plugins and themes in `tw5-plugins/` by walking for `plugin.info` files, then copies them into `tw5/plugins/` or `tw5/themes/` based on `plugin-type`.

#### Plugin validation

Each `plugin.info` must contain valid JSON with required fields:

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | TiddlyWiki title (e.g. `$:/plugins/acme/widget`) |
| `description` | string | Plugin description |

#### Segregation by type

| `plugin-type` | Target | Example |
|---------------|--------|---------|
| `"plugin"` or not set | `tw5/plugins/<author>/<name>/` | `$:/plugins/kookma/shiraz` -> `tw5/plugins/kookma/shiraz/` |
| `"theme"` | `tw5/themes/<author>/<name>/` | `$:/themes/neuroforest/basic` -> `tw5/themes/neuroforest/basic/` |

The `<author>/<name>` path is derived from the `title` field by stripping the `$:/plugins/` or `$:/themes/` prefix.

#### Example

```
tw5-plugins/
  kookma/
    shiraz/
      plugin.info
      readme.tid
      styles.tid
```

```json
{
    "title": "$:/plugins/kookma/shiraz",
    "description": "extended markups, styles, images, tables, and macros",
    "plugin-type": "plugin",
    "version": "2.9.0"
}
```

## Test

    invoke tw5.test

1. Runs `tw5.bundle` (copy editions and plugins)
2. Runs `tw5/bin/test.sh`

Non-zero exit code raises `SystemExit`.

## Tests

    pytest tests/test_tasks_tw5.py
