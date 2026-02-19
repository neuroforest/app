# NeuroDesktop

NeuroDesktop is a desktop application built on NW.js that runs a TiddlyWiki interface connected to a Neo4j graph database. It loads the custom `neuro-neo4j` TiddlyWiki edition, bootstraps the TiddlyWiki engine via a Node.js entry point (`main.js`), and preloads tiddler data from Neo4j using Bolt protocol. It supports deep linking through a custom `neuro://` protocol handler.

## Tasks

| Task | Description |
|------|-------------|
| `desktop.build` | Assemble NW.js + desktop source into a build directory |
| `desktop.run` | Launch the desktop app |
| `desktop.close` | Close the desktop app |

## Build

    invoke desktop.build
    invoke desktop.build --build-dir /tmp/mybuild

Runs its prerequisites automatically via invoke pre-tasks:

1. `setup.env` -- load config
2. `setup.rsync -c desktop` -- sync desktop source
3. `nwjs.get` -- download and extract NW.js SDK

### Stages

1. **Copy NW.js** -- rsyncs the SDK from `nwjs/v{NWJS_VERSION}/` into the build directory
2. **Copy desktop source** -- rsyncs `desktop/source/` and writes `package.json` with `APP_NAME`
3. **Install node modules** -- runs `npm install` in the build directory

### Output structure

```
build/
  nw                    # NW.js binary
  lib/                  # NW.js libraries
  source/               # Desktop source (main.js, index.html)
  package.json          # With APP_NAME applied
  node_modules/         # npm dependencies
```

## Run

    invoke desktop.run

Launches the `nw` binary as a background process. Stores PID in `nw.pid`. Exits if the binary is not found.

### Protocol handler

The `register_protocol` function handles `neuro://` deep linking:

1. Checks if NeuroDesktop is running (via `PORT`)
2. Searches for a tiddler matching the UUID
3. Opens the tiddler in the running instance

## Close

    invoke desktop.close

Reads the PID from `{app_dir}/nw.pid` and sends `SIGTERM`. The PID file is removed afterwards.

| State | Behavior |
|-------|----------|
| PID file exists, process running | Sends SIGTERM, removes PID file |
| PID file exists, process gone | Prints "already closed", removes PID file |
| No PID file | Prints "already closed" |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `APP` | | Path to app build directory |
| `APP_NAME` | `NeuroDesktop` | Application name in package.json |
| `DESKTOP_ARGS` | | Extra args passed to TiddlyWiki `--listen` |
| `NWJS_VERSION` | `0.91.0` | NW.js SDK version |
| `PORT` | `8080` | TiddlyWiki port (used by protocol handler) |

## Tests

    pytest tests/test_tasks_desktop.py
