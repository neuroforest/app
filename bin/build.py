"""
Build NeuroForest app
"""

import json
import os
import shutil

from neuro.utils import internal_utils, terminal_style

from rich.console import Console


EDITIONS_DIR = "tw5-editions"
REQUIRED_FIELDS = ["description", "plugins", "themes", "build"]


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

    missing = [field for field in REQUIRED_FIELDS if field not in info]
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


def main():
    app_path = os.getenv("NF_DIR", os.getcwd())
    with internal_utils.chdir(app_path):
        copy_tw5_editions()


if __name__ == "__main__":
    main()
