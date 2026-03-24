#!/bin/bash
set -e
mkdir -p compiled
cp -r TW-Commander/source/commander compiled/
cp -r TW-Shiraz/source/shiraz compiled/
cp -r TW-Shiraz/source/shiraz-callout compiled/
cp -r TW-Shiraz/source/shiraz-formatter compiled/
cp -r TW-Todolist/source/todolist compiled/
cp -r overrides/commander/* compiled/commander/
cp -r overrides/shiraz/* compiled/shiraz/
