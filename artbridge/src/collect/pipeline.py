"""Shared wrapper for one-command collection pipelines: log file, single-run lock and resumable error reporting."""

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import requests

# One lock for all pipelines: they append to the same data/collection/ catalog.
LOCK_PATH = Path("data/raw/collection.lock")
LOG_DIR = Path("data/logs")


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


def step(name):
    print(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} {name}", flush=True)


def run_pipeline(name, run, args):
    """Run run(args) with output also written to data/logs/; exits 0 on success and 1 on a stop."""
    if not Path("src/collect/pipeline.py").is_file():
        raise SystemExit(f"Run from the artbridge/ folder: uv run python -m src.collect.run_{name}")
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        lock = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"Another collection run seems active ({LOCK_PATH} exists). If none is active, delete that file and retry.") from None
    log_path = LOG_DIR / f"run_{name}_{datetime.now():%Y%m%d_%H%M%S}.log"
    exit_code = 1
    with log_path.open("w", encoding="utf-8") as log:
        sys.stdout = Tee(sys.__stdout__, log)
        print(f"log: {log_path}")
        try:
            run(args)
            print("\nfinished")
            exit_code = 0
        except requests.RequestException as error:
            # never print request URLs: some carry an API key
            status = error.response.status_code if error.response is not None else "network error"
            print(f"\nstopped: request failed ({status}, {type(error).__name__}); rerun the same command to resume")
        except Exception:
            print("\nstopped with an error; rerun the same command to resume after fixing it")
            traceback.print_exc(file=sys.stdout)
        finally:
            sys.stdout = sys.__stdout__
            os.close(lock)
            LOCK_PATH.unlink(missing_ok=True)
    sys.exit(exit_code)
