import json
import os
import shutil
import subprocess
import sys

import invoke

from neuro.utils import build_utils, internal_utils, network_utils, terminal_style

from tasks.actions import setup


REQUIRED_EDITION_FIELDS = ["description", "plugins", "themes"]
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


def discover_tw5_plugins(search_dir=None):
    """Find and validate plugin.info files within a directory tree.
    If search_dir is given, return the first match as (info_path, info).
    Otherwise, search all tw5-plugins and return a sorted list of (info_path, info).
    """
    single = search_dir is not None
    if not single:
        search_dir = internal_utils.get_path("nf") / "tw5-plugins"
    seen = {}
    for root, _dirs, files in os.walk(search_dir):
        if "plugin.info" in files:
            info_path = os.path.join(root, "plugin.info")
            info = validate_tw5_plugin(info_path)
            if info:
                if single:
                    return info_path, info
                title = info["title"]
                if title not in seen:
                    seen[title] = (info_path, info)
    if single:
        return None, None
    return sorted(seen.values(), key=lambda x: x[1]["title"])


def get_builtin_editions():
    """Return the set of edition names shipped with TW5 (via git, ignoring bundled copies)."""
    tw5_path = internal_utils.get_path("tw5")
    result = subprocess.run(
        ["git", "ls-tree", "--name-only", "HEAD", "editions/"],
        cwd=tw5_path, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return set()
    return {line.removeprefix("editions/") for line in result.stdout.splitlines()}


def copy_tw5_editions():
    tw5_path = internal_utils.get_path("tw5")
    editions_source = internal_utils.get_path("nf") / "tw5-editions"

    if not os.path.isdir(editions_source):
        print(f"No editions directory found at {editions_source}")
        return

    builtin = get_builtin_editions()

    for edition in sorted(os.listdir(editions_source)):
        source = os.path.join(editions_source, edition)
        if not os.path.isdir(source):
            continue
        if not validate_tw5_edition(source):
            continue
        if edition in builtin:
            print(f"  {terminal_style.WARN} TW5 edition conflict: {edition}")
            continue
        target = tw5_path / "editions" / edition
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target)


def ensure_plugin_fields(info_path, info):
    """Deduce and write missing standard fields to plugin.info."""
    changed = False
    title = info["title"]

    if "name" not in info:
        # Derive name from last segment of title, e.g. "$:/plugins/tobibeer/preview" -> "Preview"
        info["name"] = title.rsplit("/", 1)[-1].replace("-", " ").title()
        changed = True

    if "stability" not in info:
        info["stability"] = "STABILITY_2_STABLE"
        changed = True

    if "list" not in info:
        # Scan sibling .tid files for common candidates
        plugin_dir = os.path.dirname(info_path)
        candidates = ["readme", "license", "history"]
        found = [c for c in candidates if os.path.isfile(os.path.join(plugin_dir, f"{c}.tid"))]
        if found:
            info["list"] = " ".join(found)
            changed = True

    if changed:
        with open(info_path, "w") as f:
            json.dump(info, f, indent=4)
            f.write("\n")


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

        target_info_path = target / "plugin.info"
        ensure_plugin_fields(target_info_path, info)


@invoke.task(pre=[setup.env])
def bundle(c):
    """Copy TW5 editions and plugins into the TW5 tree."""
    if os.environ.get("ENVIRONMENT") == "DEVELOP":
        plugins = [p for p in setup.get_submodules() if p.startswith("tw5-plugins/")]
        setup.rsync(c, components=plugins)
    with terminal_style.step("Bundle tw5"):
        copy_tw5_editions()
        copy_tw5_plugins()


@invoke.task(pre=[setup.env])
def build(c, build_dir=None):
    """Bundle tw5 and copy it to the app build directory."""
    bundle(c)
    if not build_dir:
        build_dir = internal_utils.get_path("nf") / "build"
    if not os.path.isdir(build_dir):
        raise SystemExit(f"Build directory does not exist: {build_dir}")
    tw5_source = internal_utils.get_path("nf") / "tw5"
    build_utils.rsync_local(tw5_source, build_dir, "tw5")


@invoke.task(pre=[setup.env])
def run(c, edition="neuro-bare", port=0):
    """Launch TW5 edition with auto-restart on browser refresh."""
    tw5_path = internal_utils.get_path("tw5")
    editions_source = internal_utils.get_path("nf") / "tw5-editions"
    edition_path = editions_source / edition

    if not os.path.isdir(edition_path):
        print(f"{terminal_style.FAIL} Edition not found: {edition_path}")
        sys.exit(1)

    cmd = [
        "node", str(tw5_path / "tiddlywiki.js"), str(edition_path),
        "--listen", "port={port}", "host=127.0.0.1",
    ]
    network_utils.RestartProxy.serve(cmd, port=port)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c):
    """Copy editions/plugins, run tw5/bin/test.sh."""
    bundle(c)
    tw5_path = internal_utils.get_path("tw5")
    result = subprocess.run(["bin/test.sh"], cwd=tw5_path)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
