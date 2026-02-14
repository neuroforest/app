"""
Run NeuroForest desktop application

Verifies Neo4j connectivity, then launches the NW.js desktop app.
Supports neuro:// protocol handler for deep linking.
Stores PID in build/nw.pid for use by close.py.
"""

import logging
import os
import subprocess
import sys
import time

import neo4j

from neuro.tools.tw5api import tw_get, tw_actions
from neuro.utils import internal_utils, network_utils, terminal_style


BUILD_DIR = "build"
PID_FILE = "nw.pid"


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


def get_build_dir():
    app_path = internal_utils.get_path("app")
    return os.path.join(app_path, BUILD_DIR)


def save_pid(build_dir, pid):
    pid_path = os.path.join(build_dir, PID_FILE)
    with open(pid_path, "w") as f:
        f.write(str(pid))


def run(build_dir=None):
    if build_dir is None:
        build_dir = get_build_dir()

    nw_binary = os.path.join(build_dir, "nw")
    if not os.path.isfile(nw_binary):
        print(f"NW.js binary not found at {nw_binary}. Run build_desktop.py first.")
        sys.exit(1)

    verify_neo4j()
    process = subprocess.Popen(
        [nw_binary],
        cwd=build_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    if process.poll() is not None:
        print(f"{terminal_style.FAIL} Already running.")
        return
    save_pid(build_dir, process.pid)
    print(f"{terminal_style.SUCCESS} Running NW.js (PID {process.pid})")


def main():
    if len(sys.argv) > 1 and sys.argv[1].startswith("neuro://"):
        register_protocol(sys.argv[1])
    elif len(sys.argv) > 1:
        build_path = sys.argv[1]
        if not os.path.isabs(build_path):
            build_path = os.path.abspath(build_path)
        run(build_path)
    else:
        run()


if __name__ == "__main__":
    main()
