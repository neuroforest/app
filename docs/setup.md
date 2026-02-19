# Setup

Environment loading, submodule syncing, and branch management.

## Tasks

| Task | Description |
|------|-------------|
| `setup.env` | Load config and chdir to NF_DIR |
| `setup.rsync` | Rsync local submodules (neuro, desktop) into app/ |
| `setup.master` | Reset all submodules to master |
| `setup.develop` | Reset submodules to develop |
| `setup.branch` | Reset submodules to a specific branch |
| `setup.nenv` | Create virtualenv and install neuro |

## env

    invoke setup.env
    invoke setup.env --environment=TESTING

1. Resolves `NF_DIR` via `internal_utils.get_path("nf")`
2. Sets `ENVIRONMENT` if provided
3. Loads config via `neuro.utils.config.main()`
4. Changes working directory to `NF_DIR`

Raises `Exit` if `NF_DIR` does not exist.

All other tasks depend on `setup.env` as a pre-task.

## rsync

    invoke setup.rsync                  # sync all local submodules
    invoke setup.rsync -c neuro         # sync only neuro
    invoke setup.rsync -c desktop       # sync only desktop

Rsyncs local development copies into the app submodule directories. Source paths are resolved from environment variables (`NEURO`, `DESKTOP`).

When `neuro` is included, also runs `setup.nenv` to reinstall the package.

Local submodules: `neuro`, `desktop`.

## master / develop / branch

    invoke setup.master                         # reset all to master
    invoke setup.master -c neuro                # reset only neuro
    invoke setup.develop                        # reset all to develop
    invoke setup.branch --branch-name feat/x    # reset all to a branch
    invoke setup.branch --branch-name feat/x -c neuro

For each submodule runs:

1. `git rev-parse --short <branch>` (resolve commit)
2. `git reset --hard <branch>`
3. `git clean -fdx`

All submodules:

- `neuro`, `desktop`, `tw5`
- `tw5-plugins/neuroforest/core`, `front`, `neo4j-syncadaptor`, `basic`, `mobile`

## nenv

    invoke setup.nenv

1. Creates a virtualenv at `nenv/` via `python3 -m venv nenv`
2. Installs the local neuro package via `nenv/bin/pip install ./neuro`
3. Adds `nenv/bin` to `PATH` if not already present

## Tests

    pytest tests/test_tasks_setup.py
