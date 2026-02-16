"""
Prepare NeuroForest submodules.
"""

import configparser
import json
import os
import shutil
import subprocess

from invoke import task

from neuro.utils import build_utils, internal_utils, terminal_style

from . import setup

LOCAL_SUBMODULES = [
    "neuro",
    "desktop"
]

SUBMODULES = [
    "neuro",
    "desktop",
    "tw5",
    "tw5-plugins/neuroforest/core",
    "tw5-plugins/neuroforest/front",
    "tw5-plugins/neuroforest/neo4j-syncadaptor",
    "tw5-plugins/neuroforest/basic",
    "tw5-plugins/neuroforest/mobile",
]


class Nwjs:
    def __init__(self, version=None, url=None, overwrite=False):
        self.version = version
        self.url = url
        self.overwrite = overwrite
        app_path = internal_utils.get_path("nf")
        self.nwjs_dir = os.path.join(app_path, "desktop", "nwjs")
        self.tarfile_local = os.path.join(self.nwjs_dir, f"v{self.version}.tar.gz")
        self.tarfile_remote = f"{self.url}/v{self.version}/nwjs-sdk-v{self.version}-linux-x64.tar.gz"
        self.extract_temp = os.path.join(self.nwjs_dir, f"nwjs-sdk-v{self.version}-linux-x64")
        self.extract_final = os.path.join(self.nwjs_dir, f"v{self.version}")

    def download(self):
        os.makedirs(self.nwjs_dir, exist_ok=True)

        if os.path.isfile(self.tarfile_local) and not self.overwrite:
            print(f"{terminal_style.SUCCESS} Download v{self.version} (cached)")
            return
        if os.path.isfile(self.tarfile_local):
            os.remove(self.tarfile_local)

        self.overwrite = True
        with terminal_style.step(f"Download NW.js v{self.version}"):
            subprocess.run([
                "wget", "-c", "--show-progress", "-q",
                "-O", self.tarfile_local,
                self.tarfile_remote,
            ], check=True)

    def extract(self):
        if os.path.isdir(self.extract_final) and not self.overwrite:
            print(f"{terminal_style.SUCCESS} Extract v{self.version} (cached)")
            return
        if os.path.isdir(self.extract_final):
            shutil.rmtree(self.extract_final)

        with terminal_style.step(f"Extract NW.js v{self.version}"):
            subprocess.run([
                "tar", "-xzf", self.tarfile_local,
                "-C", self.nwjs_dir,
            ], stdout=subprocess.DEVNULL, check=True)
            os.rename(self.extract_temp, self.extract_final)


class Tw5:
    def __init__(self):
        self.required_edition_fields = ["description", "plugins", "themes", "build"]
        self.required_plugin_fields = ["title", "description"]
        self.editions_dir = os.path.join(internal_utils.get_path("nf"), "tw5-editions")
        self.plugins_dir = os.path.join(internal_utils.get_path("nf"), "tw5-plugins")

    def validate_tw5_edition(self, path):
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

        missing = [field for field in self.required_edition_fields if field not in info]
        if missing:
            print(f"  Skipping {edition}: missing fields {missing}")
            return False

        return True

    def validate_tw5_plugin(self, info_path):
        plugin = os.path.basename(os.path.dirname(info_path))

        try:
            with open(info_path) as f:
                info = json.load(f)
        except json.JSONDecodeError as e:
            print(f"  Skipping {plugin}: invalid JSON in plugin.info ({e})")
            return None

        missing = [field for field in self.required_plugin_fields if field not in info]
        if missing:
            print(f"  Skipping {plugin}: missing fields {missing}")
            return None

        return info

    def discover_tw5_plugins(self):
        results = []
        for root, _dirs, files in os.walk(self.plugins_dir):
            if "plugin.info" in files:
                info_path = os.path.join(root, "plugin.info")
                info = self.validate_tw5_plugin(info_path)
                if info:
                    results.append((info_path, info))
        return sorted(results, key=lambda x: x[1]["title"])

    def copy_tw5_editions(self):
        tw5_path = internal_utils.get_path("tw5")
        app_path = internal_utils.get_path("nf")
        editions_source = os.path.join(app_path, self.editions_dir)

        if not os.path.isdir(editions_source):
            print(f"No editions directory found at {editions_source}")
            return

        for edition in sorted(os.listdir(editions_source)):
            source = os.path.join(editions_source, edition)
            if not os.path.isdir(source):
                continue
            if not self.validate_tw5_edition(source):
                continue
            target = os.path.join(tw5_path, "editions", edition)
            with terminal_style.step(f"Copy edition {edition}"):
                shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(source, target)

    def copy_tw5_plugins(self):
        tw5_path = internal_utils.get_path("tw5")
        app_path = internal_utils.get_path("nf")

        if not os.path.isdir(self.plugins_dir):
            print(f"No plugins directory found at {self.plugins_dir}")
            return

        for info_path, info in self.discover_tw5_plugins():
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
            with terminal_style.step(f"Copy {plugin_type} {relative}"):
                shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(source_dir, target)


def reset_submodule(path, branch_name):
    """git fetch + reset --hard + clean."""
    with build_utils.chdir(path):
        with terminal_style.step(f"Reset {path} to {branch_name}"):
            subprocess.run(["git", "fetch", "origin"], check=True, capture_output=True)
            subprocess.run(
                ["git", "reset", "--hard", f"origin/{branch_name}"],
                check=True,
                capture_output=True
            )
            subprocess.run(["git", "clean", "-fdx"], check=True, capture_output=True)


@task(iterable="modules")
def rsync(c, modules):
    """Rsync local submodules (neuro, desktop) into app/."""
    if not modules:
        modules = LOCAL_SUBMODULES
    for module in modules:
        source = internal_utils.get_path(module) + "/"
        dest = internal_utils.get_path("nf") + "/" + module
        build_utils.rsync_local(source, dest, module)


@task(pre=[setup.setup], iterable="submodules")
def master(c, submodules):
    """Reset all submodules to their configured branches."""
    if not submodules:
        submodules = SUBMODULES
    for submodule in submodules:
        reset_submodule(submodule, "master")


@task(pre=[setup.setup], iterable="submodules")
def develop(c, submodules):
    """Reset NF submodules to develop."""
    if not submodules:
        submodules = SUBMODULES
    for path in submodules:
        reset_submodule(path, "develop")


@task(pre=[setup.setup], iterable="submodules")
def branch(c, branch_name, submodules):
    """Reset submodules to a branch, with fallback to configured branch."""
    if not submodules:
        submodules = SUBMODULES
    for submodules in submodules:
        reset_submodule(submodules, branch_name)


@task(pre=[setup.setup])
def nwjs(c):
    """Download and extract NW.js SDK."""
    nw = Nwjs(
        version=os.getenv("NWJS_VERSION"),
        url=os.getenv("NWJS_URL"),
    )
    nw.download()
    nw.extract()


@task(pre=[setup.setup])
def tw5(c):
    tw = Tw5()
    tw.copy_tw5_editions()
    tw.copy_tw5_plugins()
