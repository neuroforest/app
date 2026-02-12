"""
Test NeuroForest app
"""

import contextlib
import logging
import os
import subprocess
import sys

import pytest
from rich.console import Console

from neuro.utils import terminal_style, internal_utils


@contextlib.contextmanager
def chdir(path):
    old_dir = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_dir)


def prepare_neuro():
    from neuro.utils import config  # noqa: F401

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

    checkout_tw5_command = [
        "git",
        "reset",
        "--hard",
        "9e6a53755"
    ]
    with chdir(internal_utils.get_path("tw5")):
        with Console().status("[bold] reset tw5...", spinner="dots"):
            subprocess.run(checkout_tw5_command, check=True, capture_output=True)
    print(f"{terminal_style.SUCCESS} Reset tw5")


def test_neuro():
    if len(sys.argv) > 1:
        pytest_args = sys.argv[1:]
    else:
        pytest_args = ["neuro/tests"]
    pytest.main(pytest_args)


if __name__ == "__main__":
    os.environ["ENVIRONMENT"] = "TESTING"
    logging.basicConfig(level=logging.INFO)
    app_path = os.path.dirname(os.path.dirname(__file__))
    with chdir(app_path):
        prepare_neuro()
        test_neuro()

