# prepare.py

Prepare git submodules for development or deployment.

    python bin/prepare.py [option]

## Options

| Flag | Description |
|------|-------------|
| `-l`, `--local` | Rsync `neuro` and `desktop` from local repositories (default) |
| `-m`, `--master` | Reset all submodules to their default branch |
| `-d`, `--develop` | Reset neuroforest-owned submodules to `develop` |
| `-b`, `--branch <name>` | Reset all submodules to `<name>` if it exists on remote, otherwise fall back to default branch |

## Modes

### Local

Syncs `neuro` and `desktop` from their local development copies (outside `app/`) into the app submodule directories using rsync. Files matched by `.gitignore` and `.git` directories are excluded to avoid submodule conflicts.

Source paths are resolved from environment variables `NEURO` and `DESKTOP`.

### Master

Resets every submodule listed in `.gitmodules` to its configured default branch. Each submodule entry in `.gitmodules` has a `branch` field that defines its default:

```ini
[submodule "neuro"]
    path = neuro
    url = https://github.com/neuroforest/neuro
    branch = master
```

If `branch` is not set, falls back to `master`.

For each submodule this runs: `git fetch origin`, `git reset --hard origin/<branch>`, `git clean -fdx`.

### Develop

Same as master, but only affects neuroforest-owned submodules and resets them to `develop`:

- `neuro`
- `desktop`
- `tw5-plugins/neuroforest/core`
- `tw5-plugins/neuroforest/front`
- `tw5-plugins/neuroforest/neo4j-syncadaptor`
- `tw5-plugins/neuroforest/basic`
- `tw5-plugins/neuroforest/mobile`

Third-party submodules (e.g. `tw5`) are left untouched.

### Branch

Attempts to switch all submodules to the specified branch. For each submodule, checks if the branch exists on remote (`git ls-remote`). If not found, falls back to the submodule's default branch from `.gitmodules`.

## Tests

    pytest tests/test_prepare.py
