#!/bin/bash
set -e
cd tiddlywiki-codemirror6
pnpm install --frozen-lockfile
pnpm run build
