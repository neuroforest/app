"""
Load environment config and chdir to NF_DIR.
"""

import os

from invoke import task
from invoke.exceptions import Exit

from neuro.utils import config


@task
def setup(c, environment=None):
    """Load config and chdir to NF_DIR."""
    nf_dir = os.getenv("NF_DIR")
    print(f"Environment [{environment}] {nf_dir}")
    if environment:
        os.environ["ENVIRONMENT"] = environment
    config.main()
    try:
        os.chdir(nf_dir)
    except FileNotFoundError:
        raise Exit("Invalid directory: {}")

