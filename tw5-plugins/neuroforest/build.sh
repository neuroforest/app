#!/bin/bash
set -e
python3 -c "
import json, os, shutil, sys

wrapper = sys.argv[1]
with open(os.path.join(wrapper, 'build.json')) as f:
    submodules = json.load(f)['submodules']

compiled = os.path.join(wrapper, 'compiled')
for name in submodules:
    src = os.path.join(wrapper, name, 'source')
    dest = os.path.join(compiled, name)
    shutil.copytree(src, dest)

    info_path = os.path.join(dest, 'plugin.info')
    with open(info_path) as f:
        info = json.load(f)
    info['plugin-priority'] = 100
    with open(info_path, 'w') as f:
        json.dump(info, f, indent=4)
        f.write('\n')
" "$(pwd)"
