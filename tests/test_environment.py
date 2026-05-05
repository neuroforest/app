import os


def test_environment_is_testing():
    assert os.environ.get("ENVIRONMENT") == "TESTING"
