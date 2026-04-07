# Neuro

The `neuro` Python package provides core utilities, tools, and APIs used by NeuroForest platform.

Source lives at `NeuroForest/neuro/`. The copy at `app/neuro/` is synced via rsync (see [setup.md](setup.md)).

## Tasks

| Task | Description |
|------|-------------|
| `neuro.test-local` | Rsync neuro and run tests |
| `neuro.test-branch` | Set neuro branch and run tests |
| `neuro.test` | Run neuro tests |
| `neuro.test-integration` | Bundle tw5, then run neuro tests |
| `neuro.ruff` | Run ruff linter on neuro |

## Test

    invoke neuro.test-local               # rsync + test
    invoke neuro.test-branch feat/x       # set branch + test
    invoke neuro.test                     # test only

`neuro.test-local` rsyncs neuro from the local development copy, then runs `pytest neuro/tests/`.

`neuro.test-branch` resets the neuro submodule to the given branch, then runs tests.

`neuro.test` runs `pytest neuro/tests/` directly.

All test tasks accept an optional `--pytest-args` string that is split and passed to pytest.

## Ruff

    invoke neuro.ruff
    invoke neuro.ruff --ruff-args "--fix --select E"

Runs `ruff check` on the neuro package. Accepts optional `--ruff-args`.

## Test data

Neuro test data lives in `neuro/data/tests/`:

| Directory | Purpose |
|-----------|---------|
| `input/` | Input files for tests |
| `results/` | Reference files or text |
| `output/` | Files produced during a test run |

## Tests

    pytest tests/test_tasks_neuro.py

## CLI

`neuro` is a command-line tool to interact with NeuroForest from the terminal.

```
Usage: neuro [OPTIONS] COMMAND [ARGS]...

  NeuroForest command line interface.

Options:
  -v, --verbose  Enables verbose mode.
  --version      Show the version and exit.
  --help         Show this message and exit.

Commands:
  archive  archive tiddlers
  desk     NeuroDesktop
  export   export a tiddler
  geo      access tools for geospatial data
  get      NeuroAPI GET method
  merge    merge tiddlers
  mv       move file
  open     open a tiddler
  put      NeuroAPI PUT method
  random   open a random tiddler
  rename   rename tiddler
  replace  search and replace text
  search   search wiki
  taxon    import taxon
  test     test Python package neuro
```

## Reference

| Document | Content |
|----------|---------|
| [nfx.md](nfx.md) | NFX graph interchange format |
| [ontology.md](ontology.md) | Ontology module — schema, validation |
