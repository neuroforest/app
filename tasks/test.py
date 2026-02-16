from invoke import task
import subprocess

from neuro.utils import internal_utils

from . import prepare


@task(pre=[prepare.tw5])
def tw5(c):
    """Build TW5, then run tw5/bin/test.sh."""
    print(f"\n{'='*60}")
    print(f"  Running tw5 tests")
    print(f"{'='*60}\n")
    tw5_path = internal_utils.get_path("tw5")
    result = subprocess.run(["bin/test.sh"], cwd=tw5_path)
    raise SystemExit(result.returncode)


# @task
# def neuro(c, mode="local"):
#     """Run neuro tests. --mode=local|develop|master (default: local)."""
#     if mode in  VALID_MODES:
#         print(f"Unknown mode: {mode}. Use one of: {', '.join(VALID_MODES)}")
#         raise SystemExit(1)
#     setup(environment="TESTING")
#     logging.basicConfig(level=logging.INFO)
#     print(f"\n{'='*60}")
#     print(f"  Running neuro tests (mode: {mode})")
#     print(f"{'='*60}\n")
#     prepare_neuro(mode)
#     raise SystemExit(pytest.main(["neuro/tests"]))