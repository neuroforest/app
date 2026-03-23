import json
import os
import shutil
import subprocess
import sys

import invoke

from neuro.core import Tiddler
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
    for root, dirs, files in os.walk(search_dir):
        has_build = "build.json" in files
        has_plugin = "plugin.info" in files

        if has_build and has_plugin:
            print(f"  {terminal_style.WARN} Skipping {root}: build.json and plugin.info in same directory")
            continue

        if has_build:
            with open(os.path.join(root, "build.json")) as f:
                submodule = json.load(f).get("submodule", "repo")
            dirs[:] = [d for d in dirs if d != submodule]

        if not has_plugin:
            continue

        info_path = os.path.join(root, "plugin.info")
        info = validate_tw5_plugin(info_path)
        if not info:
            continue

        if single:
            return info_path, info
        title = info["title"]
        if title not in seen:
            seen[title] = (info_path, info)
    if single:
        return None, None
    return sorted(seen.values(), key=lambda x: x[1]["title"])


def unpack_plugin_json(json_path, output_dir):
    """Unpack a packed TW5 plugin JSON into exploded plugin format."""
    with open(json_path) as f:
        plugin = json.load(f)

    tiddlers = plugin.get("tiddlers", {})

    # Some packed formats embed tiddlers as JSON in the text field
    if not tiddlers and "text" in plugin:
        try:
            text_data = json.loads(plugin["text"])
            if isinstance(text_data, dict):
                tiddlers = text_data.get("tiddlers", {})
        except (json.JSONDecodeError, TypeError):
            pass

    # Determine output subdirectory from plugin title
    title = plugin.get("title", "")
    plugin_name = title.rsplit("/", 1)[-1] if title else "plugin"
    plugin_dir = os.path.join(output_dir, plugin_name)
    tiddlers_dir = os.path.join(plugin_dir, "tiddlers")
    os.makedirs(tiddlers_dir, exist_ok=True)

    # Write plugin.info — metadata without tiddler content
    info = {k: v for k, v in plugin.items() if k not in ("tiddlers", "text")}
    with open(os.path.join(plugin_dir, "plugin.info"), "w") as f:
        json.dump(info, f, indent=4)
        f.write("\n")

    # Write each tiddler as a .tid file
    for tiddler_title, tiddler in tiddlers.items():
        filename = Tiddler.get_tid_file_name(tiddler_title) + ".tid"
        filepath = os.path.join(tiddlers_dir, filename)
        text = tiddler.get("text") or ""
        with open(filepath, "w") as f:
            for key, value in tiddler.items():
                if key != "text":
                    f.write(f"{key}: {value}\n")
            f.write("\n")
            f.write(text)

    return plugin_dir


def discover_compiled_plugins(plugins_dir=None):
    """Find plugin wrappers containing build.json."""
    if plugins_dir is None:
        plugins_dir = internal_utils.get_path("nf") / "tw5-plugins"
    results = []
    for root, _dirs, files in os.walk(plugins_dir):
        if "build.json" in files:
            with open(os.path.join(root, "build.json")) as f:
                cfg = json.load(f)
            results.append((root, cfg))
    return results


def build_compiled_plugin(wrapper_dir, cfg):
    """Build a compiled TW5 plugin from its wrapper directory."""
    name = os.path.basename(wrapper_dir)
    compiled_dir = os.path.join(wrapper_dir, "compiled")

    with terminal_style.step(f"Compile {name}"):
        subprocess.run(
            ["bash", "build.sh"],
            cwd=wrapper_dir, check=True, capture_output=True,
        )
        for output_path in cfg.get("outputs", []):
            json_path = os.path.join(wrapper_dir, output_path)
            unpack_plugin_json(json_path, compiled_dir)


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
def compile(c):
    """Compile TypeScript TW5 plugins into exploded format."""
    plugins = discover_compiled_plugins()
    if not plugins:
        return
    for wrapper_dir, cfg in plugins:
        compiled_dir = os.path.join(wrapper_dir, "compiled")
        shutil.rmtree(compiled_dir, ignore_errors=True)
        build_compiled_plugin(wrapper_dir, cfg)


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
