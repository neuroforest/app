# NW.js

Download and install the NW.js SDK for building the desktop application.

## Tasks

| Task | Description |
|------|-------------|
| `nwjs.get` | Download and extract the NW.js SDK |
| `nwjs.download` | Download the NW.js SDK tarball |
| `nwjs.extract` | Extract the NW.js SDK tarball |

## Usage

    invoke nwjs.get

### 1. Download

Downloads the SDK tarball from `{NWJS_URL}/v{NWJS_VERSION}/nwjs-sdk-v{NWJS_VERSION}-linux-x64.tar.gz` into `desktop/nwjs/`. Skips if the tarball already exists (cached).

### 2. Extract

Extracts the tarball and renames the directory to a clean versioned path. Skips if the versioned directory already exists (cached).

Both stages respect the `overwrite` flag. When set, existing cached files are removed and re-downloaded/re-extracted.

## Output structure

```
desktop/
  nwjs/
    v0.91.0.tar.gz          # downloaded tarball
    v0.91.0/                 # extracted SDK
      nw
      lib/
      ...
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `NWJS_VERSION` | `0.91.0` | NW.js SDK version |
| `NWJS_URL` | `https://dl.node-webkit.org` | Download base URL |

## Tests

    pytest tests/test_tasks_nwjs.py
