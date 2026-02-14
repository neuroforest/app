# close.py

Close the NeuroForest desktop application.

    python bin/close.py [build_dir]

## Usage

    python bin/close.py                # close from default build directory (build/)
    python bin/close.py /tmp/mybuild   # close from custom build directory

## How it works

Reads the PID stored by `run.py` at `{build_dir}/nw.pid` and sends `SIGTERM` to terminate the process. The PID file is removed afterwards.

## Cases

| State | Behavior |
|-------|----------|
| PID file exists, process running | Sends SIGTERM, removes PID file |
| PID file exists, process gone | Prints "Already closed", removes PID file |
| No PID file | Prints "not running" |

## Tests

    pytest tests/test_close.py
