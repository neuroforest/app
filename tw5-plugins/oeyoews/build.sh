#!/bin/bash
set -e
cd tiddlywiki-codemirror6
pnpm install --frozen-lockfile
pnpm run build
cd ..
cp -r overrides/tiddlywiki-codemirror-6/* compiled/tiddlywiki-codemirror-6/tiddlers/
