# NeuroDesktop

NeuroDesktop is a desktop application built on NW.js that runs a TiddlyWiki interface connected to a Neo4j graph database. It loads the custom `neuro-neo4j` TiddlyWiki edition, bootstraps the TiddlyWiki engine via a Node.js entry point (`main.js`), and preloads tiddler data from Neo4j using Bolt protocol. It supports deep linking through a custom `neuro://` protocol handler.

## Tasks

| Task | Description |
|------|-------------|
| `desktop.build` | Assemble NW.js + TW5 + source into a build directory |
| `desktop.run` | Launch the desktop app |
| `desktop.close` | Close the desktop app |

## Build

    invoke desktop.build
    invoke desktop.build --build-dir /tmp/mybuild

Runs its prerequisites automatically via invoke pre-tasks:

1. `setup.env` -- load config
2. `setup.rsync -c desktop` -- sync desktop source
3. `tw5.bundle` -- copy editions and plugins into TW5 tree
4. `nwjs.get` -- download and extract NW.js SDK
5. `neurobase.start` -- start the Neo4j container

### Stages

1. **Copy NW.js** -- rsyncs the SDK from `desktop/nwjs/v{NWJS_VERSION}/` into the build directory
2. **Copy TW5** -- rsyncs the TiddlyWiki tree (`tw5/`) into the build directory
3. **Copy desktop source** -- rsyncs `desktop/source/` and writes `package.json` with `APP_NAME`
4. **Install node modules** -- runs `npm install` in the build directory

If the build directory already exists, a confirmation prompt appears before overwriting.

### Output structure

```
build/
  nw                    # NW.js binary
  lib/                  # NW.js libraries
  tw5/                  # TiddlyWiki tree
  source/               # Desktop source (main.js, index.html)
  package.json          # With APP_NAME applied
  node_modules/         # npm dependencies
```

## Run

    invoke desktop.run

1. **Verify Neo4j** -- connects using `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`. Exits if unreachable.
2. **Launch NW.js** -- starts the `nw` binary as a background process. Stores PID in `nw.pid`.

### Protocol handler

The `register_protocol` function handles `neuro://` deep linking:

1. Checks if NeuroDesktop is running (via `ND_PORT`)
2. Searches for a tiddler matching the UUID
3. Opens the tiddler in the running instance

## Close

    invoke desktop.close

Reads the PID from `{app_dir}/nw.pid` and sends `SIGTERM`. The PID file is removed afterwards.

| State | Behavior |
|-------|----------|
| PID file exists, process running | Sends SIGTERM, removes PID file |
| PID file exists, process gone | Prints "Already closed", removes PID file |
| No PID file | Prints "not running" |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `NeuroDesktop` | Application name in package.json |
| `ND_PORT` | `8080` | NeuroDesktop port |
| `NEO4J_URI` | `bolt://127.0.0.1:7687` | Bolt connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | | Neo4j password |

## Tests

    pytest tests/test_tasks_desktop.py
