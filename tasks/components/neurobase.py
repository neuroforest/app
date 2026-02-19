import os
import subprocess

import invoke

from neuro.base import docker_tools
from neuro.utils import network_utils, terminal_style

from tasks.actions import setup


@invoke.task(pre=[setup.env])
def create(c, name=None):
    """Create the neurobase docker container if it doesn't exist."""
    if name:
        base_name = name
    else:
        base_name = os.getenv("BASE_NAME")

    if docker_tools.container_exists(base_name):
        print(f"{terminal_style.SUCCESS} {base_name} exists")
        return

    with terminal_style.step(f"Creating {base_name}"):
        subprocess.run(["docker", "compose", "up", "-d"])


@invoke.task(pre=[setup.env, create])
def start(c, name=None):
    """Start the neurobase docker container and wait for Neo4j."""
    if name:
        base_name = name
    else:
        base_name = os.getenv("BASE_NAME")
    bolt_port = int(os.getenv("NEO4J_PORT_BOLT", 7687))

    if not docker_tools.container_running(base_name):
        with terminal_style.step(f"Starting {base_name}"):
            subprocess.run(["docker", "start", base_name])

    with terminal_style.step(f"Waiting for Neo4j on port {bolt_port}"):
        network_utils.wait_for_socket("127.0.0.1", bolt_port)

    print(f"{terminal_style.SUCCESS} {base_name} is running")


@invoke.task(pre=[setup.env])
def stop(c, name=None):
    """Stop the neurobase docker container."""
    if name:
        base_name = name
    else:
        base_name = os.getenv("BASE_NAME")

    if not docker_tools.container_running(base_name):
        print(f"{terminal_style.SUCCESS} {base_name} is not running")
        return

    with terminal_style.step(f"Stopping {base_name}"):
        subprocess.run(["docker", "stop", base_name])
