import os
import subprocess

import invoke

from neuro.base import docker_tools
from neuro.utils import terminal_style

from ..actions import setup


@invoke.task(pre=[setup.env])
def start(c):
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
