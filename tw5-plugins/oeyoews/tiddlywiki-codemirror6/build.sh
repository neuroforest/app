#!/bin/bash
set -e
cd repo
pnpm install --frozen-lockfile
pnpm run build
