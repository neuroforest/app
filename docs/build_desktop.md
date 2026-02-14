# build_desktop.py

Assemble the NeuroForest desktop application from NW.js SDK, TiddlyWiki, and desktop source.

    python bin/build_desktop.py [build_dir]

## Prerequisites

Run these before building the desktop app:

1. `python bin/build_nwjs.py` — download and extract the NW.js SDK
2. `python bin/build_tw5.py` — copy editions and plugins into the TW5 tree

## Usage

    python bin/build_desktop.py              # build to default directory (build/)
    python bin/build_desktop.py /tmp/mybuild  # build to custom directory

## Stages

### 1. Copy NW.js

Rsyncs the NW.js SDK from `desktop/nwjs/v{NWJS_VERSION}/` into the build directory. Aborts if the SDK is not found.

### 2. Copy TW5

Rsyncs the TiddlyWiki tree (`tw5/`) into `{build_dir}/tw5/`. Removes the `.git` directory from the copy.

### 3. Copy desktop source

Rsyncs `desktop/source/` into `{build_dir}/source/` and moves `package.json` to the build root, where NW.js expects it.

### 4. Install node modules

Runs `npm install fs neo4j-driver` in the build directory.

## Output structure

```
build/
  nw                    # NW.js binary
  lib/                  # NW.js libraries
  tw5/                  # TiddlyWiki tree (without .git)
  source/               # Desktop source (main.js, index.html)
  package.json          # Moved from source/
  node_modules/         # npm dependencies
```

## Tests

    pytest tests/test_build_desktop.py
