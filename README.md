# NeuroForest

![CI](https://github.com/neuroforest/app/actions/workflows/test.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![Neo4j](https://img.shields.io/badge/Neo4j-4581C3?logo=neo4j&logoColor=white)
![Node.js](https://img.shields.io/badge/Node.js-339933?logo=nodedotjs&logoColor=white)
![TiddlyWiki](https://img.shields.io/badge/TiddlyWiki-8B4513)

Knowledge engineering platform built on TiddlyWiki5, Neo4j, and NW.js.

## Components

| Component | Description |
|-----------|-------------|
| NeuroWiki | TiddlyWiki5 with custom editions and plugins |
| NeuroDesktop | NW.js desktop application |
| NeuroBase | Neo4j graph database backend |
| neuro | Python package — core utilities and APIs |

## Prerequisites

- Python 3.14+
- Docker + Docker Compose
- Node.js
- git, uv, ruff, rsync

## Install

> Development environment only.

`invoke` ships inside `neuro`, so `nenv/` must exist before any invoke task can run.
On a fresh clone, seed it manually:

```sh
git clone https://github.com/neuroforest/app
cd app
UV_PROJECT_ENVIRONMENT=nenv uv sync --frozen --project neuro --extra dev
nenv/bin/invoke app.build   # full build — bundles TW5, assembles desktop, creates build/nenv
nenv/bin/invoke app.run     # start NeuroBase and launch NeuroDesktop
```

## Configuration

Tasks read environment from dotenv files. Loading order:

1. `app/.env` — repo defaults (relative paths, committed)
2. `$NF_CONFIG/env` — user-wide overrides
3. `$NF_CONFIG/env.{ENVIRONMENT}` — environment-specific overrides

`NF_CONFIG` defaults to `~/.config/neuroforest/`. Use `env.develop` there for local overrides (e.g. absolute paths).

## Development workflow

```sh
# Full build (tw5 bundle + desktop + nenv)
invoke app.build

# Run (starts NeuroBase, launches NeuroDesktop)
invoke app.run

# Stop
invoke app.stop
```

### Patching without a full rebuild

```sh
invoke app.patch -c neuro          # rsync neuro source → build/nenv site-packages
invoke app.patch -c desktop        # rsync desktop source → build/source
invoke app.patch -c tw5-plugins/neuroforest/core
```

## Testing

Tests run against build output — always run `invoke app.build` first.

```sh
invoke test.local                  # all: app, neuro, tw5 + ruff
invoke test.local -c app           # app only
invoke test.local -c neuro         # neuro only
invoke test.local -c tw5           # tw5 only

invoke app.test                    # pytest tests/
invoke neuro.test                  # pytest neuro/tests/ (e2e, requires running NeuroBase)
invoke neuro.test --mode unit      # unit tests only (no DB)
invoke neuro.test --mode integration
invoke tw5.test                    # bundle + jasmine
```
