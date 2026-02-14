"""
Close NeuroForest desktop application

Reads PID from build/nw.pid and terminates the process.
"""

import os
import signal
import sys

from neuro.utils import internal_utils, terminal_style


BUILD_DIR = "build"
PID_FILE = "nw.pid"


def get_pid_path(build_dir):
    return os.path.join(build_dir, PID_FILE)


def close(build_dir=None):
    if build_dir is None:
        app_path = internal_utils.get_path("app")
        build_dir = os.path.join(app_path, BUILD_DIR)

    pid_path = get_pid_path(build_dir)

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


def main():
    if len(sys.argv) > 1:
        build_path = sys.argv[1]
        if not os.path.isabs(build_path):
            build_path = os.path.abspath(build_path)
        close(build_path)
    else:
        close()


if __name__ == "__main__":
    main()
