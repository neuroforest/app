#!/bin/bash
set -e
mkdir -p compiled

for dir in basic core front mobile neo4j-syncadaptor; do
    cp -r "$dir/source" "compiled/$dir"
    sed -i '1a\\t"plugin-priority": 100,' "compiled/$dir/plugin.info"
done
