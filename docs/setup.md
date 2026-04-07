# Setup

Environment loading and branch management.

## Tasks

| Task | Description |
|------|-------------|
| `setup.env` | Load config and chdir to APP_DIR |
| `setup.master` | Reset all submodules to master |
| `setup.develop` | Reset submodules to develop |
| `setup.branch` | Reset submodules to a specific branch |
| `setup.nenv` | Create virtualenv and install neuro |

## env

    invoke setup.env
    invoke setup.env --environment=TESTING

1. Resolves `APP_DIR` via `internal_utils.get_path("app")`
2. Sets `ENVIRONMENT` if provided
3. Loads config via `neuro.utils.config.main()`
4. Changes working directory to `APP_DIR`

Raises `Exit` if `APP_DIR` does not exist.

All other tasks depend on `setup.env` as a pre-task.

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

Neuroforest submodules:

- `neuro`
- `desktop`
- `tw5`
- `tw5-plugins/neuroforest/core`
- `tw5-plugins/neuroforest/front`
- `tw5-plugins/neuroforest/neo4j-syncadaptor`
- `tw5-plugins/neuroforest/basic`
- `tw5-plugins/neuroforest/mobile`

## nenv

    invoke setup.nenv

1. Creates a virtualenv at `$NENV` and installs neuro via `uv sync --frozen`
2. Adds `$NENV/bin` to `PATH` if not already present
