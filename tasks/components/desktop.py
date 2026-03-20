"""
Build, run and close NeuroForest desktop application.
"""

import json
import os
import signal
import subprocess
import sys
import time

import invoke

from neuro.tools.tw5api import tw_get, tw_actions
from neuro.utils import internal_utils, terminal_style, build_utils, network_utils

from tasks.actions import setup
from tasks.components import nwjs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def register_protocol(url):
    uuid = url.removeprefix("neuro://")
    nd_port = os.getenv("PORT")

    if not network_utils.is_port_in_use(nd_port):
        print("NeuroDesktop not running")
        return

    try:
        tid_title = tw_get.filter_output(f"[search:neuro.id[{uuid}]]")[0]
        tw_actions.open_tiddler(tid_title)
    except IndexError:
        print(f"Not found: {uuid}")


def get_pid_path():
    try:
        return os.path.join(os.environ["NF_STATE"], "nw.pid")
    except KeyError:
        raise invoke.exceptions.Exit("NF_STATE is not set — run setup.env first")


def save_pid(pid):
    pid_path = get_pid_path()
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    with open(pid_path, "w") as f:
        f.write(str(pid))


def get_app_dir():
    app_dir = internal_utils.get_path("build")
    if app_dir and not app_dir.is_absolute():
        app_dir = app_dir.resolve()
    return app_dir


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@invoke.task(pre=[setup.env])
def build(c, build_dir=None):
    """Assemble NW.js + TW5 + source into a build directory."""
    nwjs.get(c)
    if os.environ.get("ENVIRONMENT") == "DEVELOP":
        setup.rsync(c, components=["desktop"])

    if not build_dir:
        build_dir = internal_utils.get_path("nf") / "build"
    if not os.path.isdir(build_dir):
        raise SystemExit(f"Build directory does not exist: {build_dir}")

    # NWjs
    nwjs_version = os.getenv("NWJS_VERSION")
    nwjs_source = str(internal_utils.get_path("nf") / "nwjs" / f"v{nwjs_version}") + "/"
    build_utils.rsync_local(nwjs_source, build_dir, f"NW.js v{nwjs_version}")

    # Desktop
    desktop_source = internal_utils.get_path("nf") / "desktop" / "source"
    build_utils.rsync_local(desktop_source, build_dir, "desktop source")
    desktop_name = os.environ["DESKTOP_NAME"]
    source_pkg = os.path.join(build_dir, "source", "package.json")
    with open(source_pkg) as f:
        package = json.load(f)
    package["name"] = desktop_name
    with open(source_pkg, "w") as f:
        json.dump(package, f, indent=2)
    package["main"] = "source/index.html"
    with open(os.path.join(build_dir, "package.json"), "w") as f:
        json.dump(package, f, indent=2)

    # Window title
    index_html = os.path.join(build_dir, "source", "index.html")
    with open(index_html) as f:
        html = f.read()
    html = html.replace("<title>NeuroDesktop</title>", f"<title>{desktop_name}</title>")
    with open(index_html, "w") as f:
        f.write(html)

    # Install node modules
    with terminal_style.step("npm install"):
        subprocess.run(["npm", "install"], cwd=build_dir, check=True, capture_output=True)


@invoke.task(pre=[setup.env])
def run(c):
    """Launch NW.js desktop app. --protocol=neuro://uuid for deep linking."""
    app_dir = get_app_dir()

    # Check if already running
    pid_path = get_pid_path()
    if os.path.isfile(pid_path):
        with open(pid_path) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, 0)
            print(f"{terminal_style.SKIP} Already running (PID {pid})")
            return
        except ProcessLookupError:
            os.remove(pid_path)

    nw_binary = os.path.join(app_dir, "nw")
    if not os.path.isfile(nw_binary):
        print(f"NW.js binary not found at {nw_binary}. Run build.desktop first.")
        sys.exit(1)

    edition = os.environ["TW5_EDITION"]
    edition_path = os.path.join(app_dir, "tw5", "editions", edition)
    if not os.path.isdir(edition_path):
        print(f"{terminal_style.FAIL} Edition not found: {edition}")
        sys.exit(1)

    state_dir = os.environ.get("NF_STATE", "")
    desktop_name = os.environ["DESKTOP_NAME"].lower()
    user_data_dir = os.path.join(state_dir, desktop_name) if state_dir else os.path.join(app_dir, "user-data")
    os.makedirs(user_data_dir, exist_ok=True)
    process = subprocess.Popen(
        [nw_binary, f"--user-data-dir={user_data_dir}"],
        cwd=app_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    if process.poll() is not None:
        if process.returncode == 0:
            print(f"{terminal_style.SKIP} Already running")
        else:
            print(f"{terminal_style.FAIL} Failed to start NW.js (exit code {process.returncode})")
        return
    save_pid(process.pid)
    print(f"{terminal_style.SUCCESS} Running NW.js (PID {process.pid})")


@invoke.task(pre=[setup.env])
def close(c):
    """Close NW.js desktop app by reading PID file."""
    pid_path = get_pid_path()

    if not os.path.isfile(pid_path):
        print(f"{terminal_style.SUCCESS} NeuroDesktop already closed (no file)")
        return

    with open(pid_path) as f:
        pid = int(f.read().strip())

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"{terminal_style.SUCCESS} Closed NeuroDesktop (PID {pid})")
    except ProcessLookupError:
        print(f"{terminal_style.SUCCESS} NeuroDesktop already closed (no process)")
    finally:
        os.remove(pid_path)
