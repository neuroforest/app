# Neuro

The `neuro` Python package provides core utilities, tools, and APIs used by NeuroForest platform.

Source lives at `NeuroForest/neuro/`. The copy at `app/neuro/` is synced via rsync (see [setup.md](setup.md)).

## Tasks

| Task | Description |
|------|-------------|
| `neuro.test-local` | Rsync neuro and run tests |
| `neuro.test-branch` | Set neuro branch and run tests |
| `neuro.test` | Run neuro tests |

## Test

    invoke neuro.test-local               # rsync + test
    invoke neuro.test-branch feat/x       # set branch + test
    invoke neuro.test                     # test only

`neuro.test-local` rsyncs neuro from the local development copy, then runs `pytest neuro/tests/`.

`neuro.test-branch` resets the neuro submodule to the given branch, then runs tests.

`neuro.test` runs `pytest neuro/tests/` directly.

All accept an optional `--pytest-args` string that is split and passed to pytest.

## Tests

    pytest tests/test_tasks_neuro.py
