import json
import os
import shutil
import subprocess

import invoke

from neuro.utils import build_utils, internal_utils, terminal_style

from tasks.actions import setup


REQUIRED_EDITION_FIELDS = ["description", "plugins", "themes", "build"]
REQUIRED_PLUGIN_FIELDS = ["title", "description"]


def validate_tw5_edition(path):
    info_path = os.path.join(path, "tiddlywiki.info")
    edition = os.path.basename(path)

    if not os.path.isfile(info_path):
        print(f"  Skipping {edition}: missing tiddlywiki.info")
        return False

    try:
        with open(info_path) as f:
            info = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  Skipping {edition}: invalid JSON in tiddlywiki.info ({e})")
        return False

    missing = [field for field in REQUIRED_EDITION_FIELDS if field not in info]
    if missing:
        print(f"  Skipping {edition}: missing fields {missing}")
        return False

    return True


def validate_tw5_plugin(info_path):
    plugin = os.path.basename(os.path.dirname(info_path))

    try:
        with open(info_path) as f:
            info = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  Skipping {plugin}: invalid JSON in plugin.info ({e})")
        return None

    missing = [field for field in REQUIRED_PLUGIN_FIELDS if field not in info]
    if missing:
        print(f"  Skipping {plugin}: missing fields {missing}")
        return None

    return info


def discover_tw5_plugins():
    plugins_dir = internal_utils.get_path("nf") / "tw5-plugins"
    results = []
    for root, _dirs, files in os.walk(plugins_dir):
        if "plugin.info" in files:
            info_path = os.path.join(root, "plugin.info")
            info = validate_tw5_plugin(info_path)
            if info:
                results.append((info_path, info))
    return sorted(results, key=lambda x: x[1]["title"])


def copy_tw5_editions():
    tw5_path = internal_utils.get_path("tw5")
    editions_source = internal_utils.get_path("nf") / "tw5-editions"

    if not os.path.isdir(editions_source):
        print(f"No editions directory found at {editions_source}")
        return

    for edition in sorted(os.listdir(editions_source)):
        source = os.path.join(editions_source, edition)
        if not os.path.isdir(source):
            continue
        if not validate_tw5_edition(source):
            continue
        target = tw5_path / "editions" / edition
        with terminal_style.step(f"Copy edition {edition}"):
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(source, target)


def copy_tw5_plugins():
    tw5_path = internal_utils.get_path("tw5")
    plugins_dir = internal_utils.get_path("nf") / "tw5-plugins"

    if not os.path.isdir(plugins_dir):
        print(f"No plugins directory found at {plugins_dir}")
        return

    for info_path, info in discover_tw5_plugins():
        plugin_type = info.get("plugin-type", "plugin")
        title = info["title"]

        if plugin_type == "theme":
            relative = title.removeprefix("$:/themes/")
            target_base = "themes"
        else:
            relative = title.removeprefix("$:/plugins/")
            target_base = "plugins"

        source_dir = os.path.dirname(info_path)
        target = tw5_path / target_base / relative
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source_dir, target)


@invoke.task(pre=[setup.env])
def bundle(c):
    """Copy TW5 editions and plugins into the TW5 tree."""
    with terminal_style.step("Bundle tw5"):
        copy_tw5_editions()
        copy_tw5_plugins()


@invoke.task(pre=[setup.env, bundle])
def build(c, build_dir=None):
    """Bundle tw5 and copy it to the app build directory."""
    if not build_dir:
        build_dir = internal_utils.get_path("nf") / "app"
    if not os.path.isdir(build_dir):
        raise SystemExit(f"Build directory does not exist: {build_dir}")
    tw5_source = internal_utils.get_path("nf") / "tw5"
    build_utils.rsync_local(tw5_source, build_dir, "tw5")


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c):
    """Copy editions/plugins, run tw5/bin/test.sh."""
    bundle(c)
    tw5_path = internal_utils.get_path("tw5")
    result = subprocess.run(["bin/test.sh"], cwd=tw5_path)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
