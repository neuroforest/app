import json
import os
import shutil
import subprocess

from invoke import call, task, exceptions

from neuro.base import docker_tools
from neuro.utils import internal_utils, terminal_style, build_utils, terminal_components

from . import setup, prepare


@task(pre=[setup.setup])
def neurobase(c):
    """Start or create the neurobase docker container."""
    container_name = os.getenv("BASE_NAME")
    if docker_tools.container_running(container_name):
        print(f"{terminal_style.SUCCESS} Container '{container_name}' is running.")
        return

    if docker_tools.container_exists(container_name):
        print(f"Starting existing container '{container_name}'...")
        subprocess.run(["docker", "start", container_name])
    else:
        print(f"Creating container '{container_name}'...")
        subprocess.run(["docker", "compose", "up", "-d"])


@task(pre=[setup.setup, call(prepare.rsync, modules=["desktop"]), prepare.tw5, prepare.nwjs, neurobase])
def desktop(c, build_dir=None):
    """Assemble NW.js + TW5 + source into a build directory."""
    if not build_dir:
        build_dir = internal_utils.get_path("nf") + "/app"
    if os.path.exists(build_dir):
        if terminal_components.bool_prompt(f"Rewrite {build_dir}?"):
            shutil.rmtree(build_dir, ignore_errors=True)
        else:
            exceptions.Exit("Aborting...")

    # NWjs
    nwjs_version = os.getenv("NWJS_VERSION")
    nwjs_source = os.path.join(internal_utils.get_path("nf"), "desktop", "nwjs", f"v{nwjs_version}") + "/"
    build_utils.rsync_local(nwjs_source, build_dir, f"NW.js v{nwjs_version}")

    # TiddlyWiki5
    tw5_source = os.path.join(internal_utils.get_path("nf"), "tw5")
    build_utils.rsync_local(tw5_source, build_dir, "tw5")

    # Desktop
    desktop_source = os.path.join(internal_utils.get_path("nf"), "desktop", "source")
    build_utils.rsync_local(desktop_source, build_dir, "desktop source")
    source_pkg = os.path.join(build_dir, "source", "package.json")
    with open(source_pkg) as f:
        package = json.load(f)
    package["name"] = os.getenv("APP_NAME", "NeuroDesktop")
    with open(os.path.join(build_dir, "package.json"), "w") as f:
        json.dump(package, f, indent=2)

    # Install node modules
    with terminal_style.step("npm install"):
        subprocess.run(["npm", "install"], cwd=build_dir, check=True)
