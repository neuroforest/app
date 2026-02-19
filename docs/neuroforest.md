# NeuroForest

NeuroForest is an open-source knowledge engineering platform focused on improving the capacity and efficiency of the human mind.

It applies the object-oriented philosophy to knowledge.

## Components

| Component | Description |
|-----------|-------------|
| [NeuroWiki](#neurowiki) | TiddlyWiki integrated into the NeuroForest platform |
| [NeuroDesktop](desktop.md) | NW.js desktop application for running NeuroWiki locally |
| [NeuroBase](neurobase.md) | Graph database backend (Neo4j) |

## NeuroWiki

NeuroWiki is TiddlyWiki5 integrated into the NeuroForest platform. It combines TiddlyWiki's non-linear notebook interface with NeuroForest's custom editions, plugins, and Neo4j graph storage.

NeuroWiki runs inside [NeuroDesktop](desktop.md) and stores its data in [NeuroBase](neurobase.md).



## Architecture

```
NeuroDesktop (NW.js)
  |
  +-- NeuroWiki (TiddlyWiki + custom editions/plugins)
  |     |
  |     +-- tw5-editions/     custom TiddlyWiki editions
  |     +-- tw5-plugins/      custom plugins and themes
  |
  +-- NeuroBase (Neo4j)
        |
        +-- Bolt protocol     tiddler storage and queries
        +-- APOC plugins      advanced graph operations
```

## Quick start

```sh
# 1. Load config
invoke setup.env

# 2. Sync submodules from local development copies
invoke setup.master

# 3. Build and launch
invoke app.build     # creates neurobase, builds tw5 and desktop
invoke app.run       # starts neurobase and launches desktop

# 4. Close
invoke app.stop      # closes desktop and stops neurobase
```

## Tasks

    invoke --list

### App

| Task | Description |
|------|-------------|
| `app.build` | Create neurobase, build tw5 and desktop |
| `app.run` | Start neurobase and launch desktop |
| `app.stop` | Close desktop and stop neurobase |
| `app.test` | Run app tests (pytest tests/) |

### Actions

| Task | Description |
|------|-------------|
| `setup.env` | Load config and chdir to NF_DIR |
| `setup.rsync` | Rsync local submodules (neuro, desktop) |
| `setup.master` | Reset all submodules to master |
| `setup.develop` | Reset submodules to develop |
| `setup.branch` | Reset submodules to a specific branch |
| `test.local` | Run all local component tests (app, neuro, tw5) |
| `test.production` | Run production tests (stub) |

### Components

| Task | Description |
|------|-------------|
| `neuro.test-local` | Rsync neuro and run tests |
| `neuro.test-branch` | Set neuro branch and run tests |
| `neuro.test` | Run neuro tests |
| `tw5.bundle` | Copy editions and plugins into the TW5 tree |
| `tw5.build` | Bundle and copy TW5 tree to app build directory |
| `tw5.test` | Bundle and run TW5 tests |
| `neurobase.create` | Create the Neo4j container |
| `neurobase.start` | Start the Neo4j container and wait for Bolt |
| `neurobase.stop` | Stop the Neo4j container |
| `nwjs.download` | Download NW.js SDK |
| `nwjs.extract` | Extract NW.js SDK |
| `nwjs.get` | Download and extract NW.js SDK |
| `desktop.build` | Assemble NW.js + TW5 + source |
| `desktop.run` | Launch the desktop app |
| `desktop.close` | Close the desktop app |

## Testing

    invoke test.local                   # run all (app, neuro, tw5)
    invoke test.local -c app -c neuro   # run specific components
    invoke app.test                     # run app tests only

All test tasks set `ENVIRONMENT=TESTING`, which loads `.env.testing` instead of `.env`.

See [configuration.md](configuration.md) for environment variable reference.

## Dependencies

- Python 3.14+
- Neo4j
- Docker
- git
- Node.js / npm
- TiddlyWiki5
- NW.js SDK

## Documentation

| Document | Content |
|----------|---------|
| [neuroforest.md](neuroforest.md) | This document -- overview and quick start |
| [setup.md](setup.md) | Setup -- env loading, rsync, branch management |
| [configuration.md](configuration.md) | Environment variables, dotenv files, setup |
| [neuro.md](neuro.md) | Neuro Python package -- sync, submodules, tests |
| [tw5.md](tw5.md) | TW5 editions, plugins, and testing |
| [neurobase.md](neurobase.md) | NeuroBase -- Neo4j Docker container |
| [nwjs.md](nwjs.md) | NW.js SDK download and extraction |
| [desktop.md](desktop.md) | NeuroDesktop -- build, run, close |
