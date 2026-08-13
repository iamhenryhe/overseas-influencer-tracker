from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_heartbeat(
    path: Path,
    *,
    run_id: str,
    iteration: int,
    status: str,
    exit_code: int,
) -> None:
    payload = {
        "updated_at": utc_now(),
        "run_id": run_id,
        "iteration": iteration,
        "status": status,
        "exit_code": exit_code,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a tracker heartbeat file")
    parser.add_argument("--file", default=os.getenv("HEARTBEAT_FILE", "monitor_heartbeat.json"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--iteration", type=int, required=True)
    parser.add_argument("--status", choices=("starting", "ok", "error", "finished"), required=True)
    parser.add_argument("--exit-code", type=int, default=0)
    args = parser.parse_args()
    write_heartbeat(
        Path(args.file),
        run_id=args.run_id,
        iteration=args.iteration,
        status=args.status,
        exit_code=args.exit_code,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
