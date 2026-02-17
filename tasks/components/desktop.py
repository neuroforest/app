"""
Build, run and close NeuroForest desktop application.
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time

import neo4j

from invoke import call, task, exceptions

from neuro.tools.tw5api import tw_get, tw_actions
from neuro.utils import internal_utils, terminal_style, build_utils, network_utils, terminal_components

from ..actions import setup
from . import neurobase, nwjs, tw5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def verify_neo4j():
    logging.getLogger("neo4j").setLevel(logging.ERROR)
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))

    try:
        driver.verify_connectivity()
        print(f"{terminal_style.SUCCESS} Neo4j connected ({uri})")
    except neo4j.exceptions.ServiceUnavailable:
        print(f"Neo4j inaccessible: {uri}")
        sys.exit(1)
    except Exception as e:
        print(f"Neo4j inaccessible: {e}")
        sys.exit(1)
    finally:
        driver.close()


def register_protocol(url):
    uuid = url.removeprefix("neuro://")
    nd_port = os.getenv("ND_PORT")

    if not network_utils.is_port_in_use(nd_port):
        print("NeuroDesktop not running")
        return

    try:
        tid_title = tw_get.filter_output(f"[search:neuro.id[{uuid}]]")[0]
        tw_actions.open_tiddler(tid_title)
    except IndexError:
        print(f"Not found: {uuid}")


def save_pid(build_dir, pid):
    pid_path = os.path.join(build_dir, "nw.pid")
    with open(pid_path, "w") as f:
        f.write(str(pid))


def get_app_dir():
    app_dir = internal_utils.get_path("app")
    if app_dir and not os.path.isabs(app_dir):
        app_dir = os.path.abspath(app_dir)
    return app_dir


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@task(pre=[setup.env, call(setup.rsync, components=["desktop"]), tw5.bundle, nwjs.get, neurobase.start])
def build(c, build_dir=None):
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
    nwjs_source = os.path.join(internal_utils.get_path("nf"), "nwjs", f"v{nwjs_version}") + "/"
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


@task(pre=[setup.env])
def run(c):
    """Launch NW.js desktop app. --protocol=neuro://uuid for deep linking."""
    app_dir = get_app_dir()

    nw_binary = os.path.join(app_dir, "nw")
    if not os.path.isfile(nw_binary):
        print(f"NW.js binary not found at {nw_binary}. Run build.desktop first.")
        sys.exit(1)

    verify_neo4j()
    process = subprocess.Popen(
        [nw_binary],
        cwd=app_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    if process.poll() is not None:
        print(f"{terminal_style.FAIL} Already running.")
        return
    save_pid(app_dir, process.pid)
    print(f"{terminal_style.SUCCESS} Running NW.js (PID {process.pid})")


@task(pre=[setup.env])
def close(c):
    """Close NW.js desktop app by reading PID file."""
    app_dir = get_app_dir()
    pid_path = os.path.join(app_dir, "nw.pid")

    if not os.path.isfile(pid_path):
        print("No PID file found. NeuroDesktop is not running.")
        return

    with open(pid_path) as f:
        pid = int(f.read().strip())

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"{terminal_style.SUCCESS} Closed NeuroDesktop (PID {pid})")
    except ProcessLookupError:
        print(f"Process {pid} not found. Already closed.")
    finally:
        os.remove(pid_path)
