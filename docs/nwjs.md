# nwjs.py

Download and install the NW.js SDK for building the desktop application.

    python bin/nwjs.py

## Configuration

Uses environment variables from `.env` / `.env.defaults`:

| Variable | Description | Example |
|----------|-------------|---------|
| `NWJS_VERSION` | NW.js SDK version to install | `0.91.0` |
| `NWJS_URL` | Base URL for NW.js downloads | `https://dl.node-webkit.org` |

## Stages

### 1. Download

Downloads the NW.js SDK tarball from `{NWJS_URL}/v{NWJS_VERSION}/nwjs-sdk-v{NWJS_VERSION}-linux-x64.tar.gz` into `desktop/nwjs/`. Skips if the tarball already exists (cached).

### 2. Extract

Extracts the tarball and renames the directory to a clean versioned path. Skips if the versioned directory already exists (cached).

### Output structure

```
desktop/
  nwjs/
    v0.91.0.tar.gz          # downloaded tarball
    v0.91.0/                 # extracted SDK
      nw
      lib/
      ...
```

### Overwrite

Both stages respect the `overwrite` flag. When set, existing cached files are removed and re-downloaded/re-extracted.

## Tests

    pytest tests/test_nwjs.py
