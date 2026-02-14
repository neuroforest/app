"""
Test NeuroForest app
"""

import logging
import os
import subprocess
import sys

import pytest
from rich.console import Console

from neuro.utils import terminal_style, internal_utils


def reset_submodule(path, branch):
    with internal_utils.chdir(path):
        subprocess.run(["git", "fetch", "origin"], check=True)
        subprocess.run(["git", "reset", "--hard", f"origin/{branch}"], check=True)
        subprocess.run(["git", "clean", "-fdx"], check=True)


def prepare_neuro_local():
    rsync_command = [
        "rsync",
        "-va",
        internal_utils.get_path("neuro"),
        internal_utils.get_path("app"),
        "--delete"
    ]
    with Console().status("[bold] Sync neuro...", spinner="dots"):
        subprocess.run(rsync_command, check=True, capture_output=True)
    print(f"{terminal_style.SUCCESS} Sync neuro")

    install_command = [
        internal_utils.get_path("app") + "/nenv/bin/pip",
        "install",
        internal_utils.get_path("app") + "/neuro"
    ]
    with Console().status("[bold] Install neuro...", spinner="dots"):
        subprocess.run(install_command, check=True, capture_output=True)
    print(f"{terminal_style.SUCCESS} Install neuro")


def test_neuro(mode, pytest_args):
    if mode == "local":
        prepare_neuro_local()
    elif mode == "develop":
        reset_submodule(internal_utils.get_path("app") + "/neuro", "develop")
    elif mode == "master":
        reset_submodule(internal_utils.get_path("app") + "/neuro", "master")
    else:
        print("Mode not supported:", mode)

    if len(pytest_args) == 0:
        pytest_args = ["neuro/tests"]
    pytest.main(pytest_args)


def parse_arguments():
    args = sys.argv[1:]

    if len(args) == 0:
        return "local", []
    elif args[0] in ["-l", "--local"]:
        return "local", args[1:]
    elif args[0] in ["-d", "--develop"]:
        return "develop", args[1:]
    elif args[0] in ["-m", "--master"]:
        return "master", args[1:]
    else:
        return "local", args


def main():
    logging.basicConfig(level=logging.INFO)
    mode, pytest_args = parse_arguments()
    os.environ["ENVIRONMENT"] = "TESTING"
    app_path = os.getenv("NF_DIR")
    with internal_utils.chdir(app_path):
        from neuro.utils import config
        config.main()
        test_neuro(mode, pytest_args)


if __name__ == "__main__":
    main()
