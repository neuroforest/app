# Configuration

Environment variables are managed through dotenv files in the `app/` directory.

## Files

| File | Purpose |
|------|---------|
| `.env.defaults` | Default values, committed to the repository |
| `.env` | Local overrides, not committed (machine-specific paths, ports, API keys) |
| `.env.testing` | Overrides applied when `ENVIRONMENT=TESTING` |

Loading order: `.env.defaults` first, then `.env` (or `.env.testing`) with override. This is handled by `neuro.utils.config` and triggered by the `setup.env` task.

## Setup

All tasks depend on `setup.env` as a pre-task. It loads config and changes to `NF_DIR`:

    invoke setup.env
    invoke setup.env --environment=TESTING

## Variable reference

### General

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `NeuroDesktop` | Application name |
| `HOST` | `127.0.0.1` | Server bind address |
| `PORT` | `8080` | Server port |
| `TEST_PORT` | `8069` | Test server port |
| `LOGGING` | `WARNING` | Log level |
| `LOGGING_FORMAT` | `%(levelname)s %(name)s: %(message)s` | Log format string |
| `ENVIRONMENT` | `DEVELOP` | Active environment (`DEVELOP`, `TESTING`) |

### Paths

| Variable | Default | Description |
|----------|---------|-------------|
| `APP` | `app` | Application root |
| `NF` | `.` | NeuroForest root |
| `DESIGN` | `design` | Design directory |
| `DESKTOP` | `desktop` | Desktop submodule |
| `NEURO` | `neuro` | Neuro submodule |
| `RESOURCES` | `neuro/resources` | Resources directory |
| `STORAGE` | `storage` | Storage directory |
| `TW5` | `tw5` | TiddlyWiki5 submodule |

In `.env`, these are typically set to absolute paths. In `.env.defaults`, they are relative to the app root.

### NeuroDesktop

| Variable | Default | Description |
|----------|---------|-------------|
| `NWJS_URL` | `https://dl.node-webkit.org` | NW.js download URL |
| `NWJS_VERSION` | `0.91.0` | NW.js version |

### NeuroBase

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_NAME` | `neurobase` | Docker project/container name |
| `NBASE_IMAGE` | `nbase` | Docker image name |
| `NBASE_VERSION` | `1.0` | Docker image tag |
| `NEO4J_VERSION` | `5.26.7` | Neo4j base image version |
| `NEO4J_PORT_HTTP` | `7474` | Neo4j Browser port |
| `NEO4J_PORT_BOLT` | `7687` | Neo4j Bolt port |
| `NEO4J_URI` | `bolt://127.0.0.1:7687` | Bolt connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | | Neo4j password |

### API keys

| Variable | Default | Description |
|----------|---------|-------------|
| `NCBI_API_KEY` | | NCBI E-utilities API key |

## Notes

- Variable interpolation (`${VAR}`) does not work in `.env` files. Use hardcoded values.
- The `NF_DIR` variable points to the NeuroForest root and is expected to be set externally (e.g. by the shell environment or launcher script).
