"""
Build NeuroForest app
"""

import json
import os
import shutil

from rich.console import Console

from neuro.utils import internal_utils, terminal_style


EDITIONS_DIR = "tw5-editions"
PLUGINS_DIR = "tw5-plugins"
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


def copy_tw5_editions():
    console = Console()
    tw5_path = internal_utils.get_path("tw5")
    app_path = internal_utils.get_path("app")
    editions_source = os.path.join(app_path, EDITIONS_DIR)

    if not os.path.isdir(editions_source):
        print(f"No editions directory found at {editions_source}")
        return

    for edition in sorted(os.listdir(editions_source)):
        source = os.path.join(editions_source, edition)
        if not os.path.isdir(source):
            continue
        if not validate_tw5_edition(source):
            continue
        target = os.path.join(tw5_path, "editions", edition)
        with console.status(f"[bold] Copy edition {edition}...", spinner="dots"):
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(source, target)
        print(f"{terminal_style.SUCCESS} Copy edition {edition}")


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


def discover_tw5_plugins(plugins_source):
    results = []
    for root, _dirs, files in os.walk(plugins_source):
        if "plugin.info" in files:
            info_path = os.path.join(root, "plugin.info")
            info = validate_tw5_plugin(info_path)
            if info:
                results.append((info_path, info))
    return sorted(results, key=lambda x: x[1]["title"])


def copy_tw5_plugins():
    console = Console()
    tw5_path = internal_utils.get_path("tw5")
    app_path = internal_utils.get_path("app")
    plugins_source = os.path.join(app_path, PLUGINS_DIR)

    if not os.path.isdir(plugins_source):
        print(f"No plugins directory found at {plugins_source}")
        return

    for info_path, info in discover_tw5_plugins(plugins_source):
        plugin_type = info.get("plugin-type", "plugin")
        title = info["title"]

        if plugin_type == "theme":
            relative = title.removeprefix("$:/themes/")
            target_base = "themes"
        else:
            relative = title.removeprefix("$:/plugins/")
            target_base = "plugins"

        source_dir = os.path.dirname(info_path)
        target = os.path.join(tw5_path, target_base, relative)
        with console.status(f"[bold] Copy {plugin_type} {relative}...", spinner="dots"):
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(source_dir, target)
        print(f"{terminal_style.SUCCESS} Copy {plugin_type} {relative}")


def main():
    app_path = os.getenv("NF_DIR", os.getcwd())
    with internal_utils.chdir(app_path):
        copy_tw5_editions()
        copy_tw5_plugins()


if __name__ == "__main__":
    main()
