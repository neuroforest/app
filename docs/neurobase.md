# neurobase.py

Manage the NeuroBase Neo4j container.

    python bin/neurobase.py

## Behavior

1. If the container is already running, prints a message and exits
2. If the container exists but is stopped, starts it with `docker start`
3. If the container does not exist, creates it with `docker compose up -d`

The container name is read from the `BASE_NAME` environment variable.

## Docker Compose

The `docker-compose.yml` defines a single service `nbase` built from the local `Dockerfile`. All values are configured through environment variables:

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

### Volumes

Two named volumes are created per project, prefixed with `BASE_NAME`:

| Volume | Mount | Purpose |
|--------|-------|---------|
| `${BASE_NAME}-data` | `/data` | Neo4j database files |
| `${BASE_NAME}-logs` | `/logs` | Neo4j log files |

Multiple projects with different `BASE_NAME` values can run side by side without volume conflicts.

### Ports

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

The Neo4j version is passed as a build argument from `NEO4J_VERSION` in `.env`.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_NAME` | `neurobase` | Compose project name, container name, volume prefix |
| `NBASE_IMAGE` | `nbase` | Docker image name |
| `NBASE_VERSION` | `1.0` | Docker image tag |
| `NEO4J_VERSION` | `5.26.7` | Neo4j base image version |
| `NEO4J_PORT_HTTP` | `7474` | Host port for Neo4j Browser |
| `NEO4J_PORT_BOLT` | `7687` | Host port for Bolt protocol |
| `NEO4J_PASSWORD` | | Neo4j authentication password |
| `NEO4J_URI` | `bolt://127.0.0.1:7687` | Bolt connection URI (used by application code) |
