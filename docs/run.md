# run.py

Run the NeuroForest desktop application.

    python bin/run.py [build_dir]

## Usage

    python bin/run.py                # run from default build directory (build/)
    python bin/run.py /tmp/mybuild   # run from custom build directory
    python bin/run.py neuro://uuid   # handle neuro:// protocol deep link

## Prerequisites

1. `python bin/build_desktop.py` — assemble the desktop build
2. `python bin/build_neurobase.py` — start the Neo4j container

## Stages

### 1. Verify Neo4j

Connects to Neo4j using `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` from the environment. Exits if the database is unreachable.

### 2. Launch NW.js

Starts the `nw` binary from the build directory as a background process. Exits if the binary is not found.

## Protocol handler

When invoked with a `neuro://` URL, the script acts as a protocol handler for deep linking:

1. Checks if NeuroDesktop is running (via `ND_PORT`)
2. Searches for a tiddler matching the UUID
3. Opens the tiddler in the running instance

## Configuration

| Variable | Description | Example |
|----------|-------------|---------|
| `NEO4J_URI` | Neo4j connection URI | `bolt://127.0.0.1:7687` |
| `NEO4J_USER` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | |
| `ND_PORT` | NeuroDesktop port for protocol handler | `8080` |

## Tests

    pytest tests/test_run.py
