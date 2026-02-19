# NeuroBase

NeuroBase is a containerized Neo4j graph database that serves as the persistent storage backend for NeuroDesktop. It is deployed via Docker Compose with APOC plugins enabled. NeuroDesktop connects to it over Bolt protocol. Multiple instances can run side by side using different `BASE_NAME` values.

## Tasks

| Task | Description |
|------|-------------|
| `neurobase.create` | Create the Neo4j container if it doesn't exist |
| `neurobase.start` | Start the Neo4j container and wait for Bolt readiness |
| `neurobase.stop` | Stop the Neo4j container |
| `neurobase.backup` | Stop and backup the container and data |
| `neurobase.delete` | Stop and remove the container and its volumes |

All tasks accept an optional `--name` parameter that overrides `BASE_NAME`.

## Create

    invoke neurobase.create
    invoke neurobase.create --name base-name

1. If the container already exists, prints a message and exits
2. Otherwise creates it with `docker compose up -d`

## Start

    invoke neurobase.start

## Backup

    invoke neurobase.backup
    invoke neurobase.backup --name base-name

Stops the container (pre-task), then backs up the container image and `/data` volume to the archive directory.

## Delete

    invoke neurobase.delete
    invoke neurobase.delete --name base-name

Stops the container (pre-task), then prompts for confirmation before removing the container and its associated volumes.

## Docker Compose

The `docker-compose.yml` defines a single service `nbase` built from the local `Dockerfile`:

```yaml
name: ${BASE_NAME}

services:
  nbase:
    build:
      context: .
      args:
        NEO4J_BASE_VERSION: ${NEO4J_VERSION}
    image: ${NBASE_IMAGE}:${NBASE_VERSION}
    container_name: ${BASE_NAME}
```

## Volumes

| Volume | Mount | Purpose |
|--------|-------|---------|
| `${BASE_NAME}-data` | `/data` | Neo4j database files |
| `${BASE_NAME}-logs` | `/logs` | Neo4j log files |

Multiple projects with different `BASE_NAME` values can run side by side without volume conflicts.

## Ports

| Variable | Default | Container port |
|----------|---------|----------------|
| `NEO4J_PORT_HTTP` | `7474` | `7474` (Browser) |
| `NEO4J_PORT_BOLT` | `7687` | `7687` (Bolt) |

## Dockerfile

Builds on top of the official Neo4j image with APOC plugins enabled:

```dockerfile
ARG NEO4J_BASE_VERSION
FROM neo4j:${NEO4J_BASE_VERSION}
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_NAME` | `neurobase` | Compose project name, container name, volume prefix |
| `NBASE_IMAGE` | `nbase` | Docker image name |
| `NBASE_VERSION` | `1.0` | Docker image tag |
| `NEO4J_VERSION` | `5.26.7` | Neo4j base image version |
| `NEO4J_PORT_HTTP` | `7474` | Host port for Neo4j Browser |
| `NEO4J_PORT_BOLT` | `7687` | Host port for Bolt protocol |
| `NEO4J_PASSWORD` | | Neo4j authentication password |
| `NEO4J_URI` | `bolt://127.0.0.1:7687` | Bolt connection URI |

## Tests

    pytest tests/test_tasks_neurobase.py
