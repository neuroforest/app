import logging
import os
import subprocess
import sys
import time

import invoke
import neo4j

from neuro.base import docker_tools
from neuro.utils import network_utils, terminal_style

from tasks.actions import setup


def verify_neo4j(timeout=30):
    logging.getLogger("neo4j").setLevel(logging.ERROR)
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    deadline = time.monotonic() + timeout
    while True:
        driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
        try:
            driver.verify_connectivity()
            return
        except (neo4j.exceptions.ServiceUnavailable, Exception):
            if time.monotonic() >= deadline:
                print(f"Neo4j inaccessible: {uri}")
                sys.exit(1)
            time.sleep(0.5)
        finally:
            driver.close()


@invoke.task(pre=[setup.env])
def create(c, name=None):
    """Create the neurobase docker container if it doesn't exist."""
    if name:
        base_name = name
    else:
        base_name = os.getenv("BASE_NAME")

    if docker_tools.container_exists(base_name):
        return

    with terminal_style.step(f"Create NeuroBase instance: {base_name}"):
        subprocess.run(["docker", "compose", "up", "-d"], capture_output=True)


@invoke.task(pre=[setup.env, create])
def start(c, name=None):
    """Start the neurobase docker container and wait for Neo4j."""
    if name:
        base_name = name
    else:
        base_name = os.getenv("BASE_NAME")
    bolt_port = int(os.getenv("NEO4J_PORT_BOLT", 7687))

    if not docker_tools.container_running(base_name):
        with terminal_style.step(f"Start NeuroBase instance: {base_name}"):
            subprocess.run(["docker", "start", base_name], capture_output=True)

    with terminal_style.step(f"Waiting for Neo4j on port {bolt_port}", display=False):
        network_utils.wait_for_socket("127.0.0.1", bolt_port)
        verify_neo4j()

    print(f"{terminal_style.SUCCESS} NeuroBase instance is running: {base_name}")


@invoke.task(pre=[setup.env])
def stop(c, name=None):
    """Stop the neurobase docker container."""
    if name:
        base_name = name
    else:
        base_name = os.getenv("BASE_NAME")

    if not docker_tools.container_running(base_name):
        print(f"{terminal_style.SUCCESS} Already stopped: {base_name}")
        return

    with terminal_style.step(f"Stop NeuroBase instance: {base_name}"):
        subprocess.run(["docker", "stop", base_name], capture_output=True)
