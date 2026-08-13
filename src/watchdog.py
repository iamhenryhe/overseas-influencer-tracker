from __future__ import annotations

import argparse
import html
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .push import send_to_all

LOG = logging.getLogger("tracker-watchdog")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOG.error("cannot read %s: %s", path, exc)
        return dict(default)
    return value if isinstance(value, dict) else dict(default)


def evaluate_heartbeat(
    heartbeat: dict[str, Any],
    *,
    now: datetime,
    stale_after_seconds: int,
) -> tuple[str, str] | None:
    if not heartbeat:
        return "missing", "还没有收到跟踪器心跳，跟踪任务可能没有启动。"

    updated_at = _parse_timestamp(heartbeat.get("updated_at"))
    if updated_at is None:
        return "invalid", "心跳文件的更新时间无法解析，跟踪器状态异常。"

    age_seconds = max(0, int((now - updated_at).total_seconds()))
    if age_seconds > stale_after_seconds:
        minutes = age_seconds // 60
        return "stale", f"已经 {minutes} 分钟没有收到心跳，跟踪器可能停止或卡住。"

    try:
        exit_code = int(heartbeat.get("exit_code", 0))
    except (TypeError, ValueError):
        exit_code = 1
    if heartbeat.get("status") == "error" or exit_code != 0:
        iteration = heartbeat.get("iteration", "未知")
        return "check_failed", f"跟踪器仍在运行，但第 {iteration} 次检查失败；请查看 GitHub Actions 日志。"
    return None


def _tokens() -> tuple[str, ...]:
    raw = os.getenv("PUSHPLUS_TOKENS") or os.getenv("PUSHPLUS_TOKEN") or ""
    return tuple(dict.fromkeys(token.strip() for token in raw.split(",") if token.strip()))


def _notify(title: str, message: str) -> bool:
    tokens = _tokens()
    if not tokens:
        LOG.error("PUSHPLUS_TOKENS is missing; cannot send watchdog notification")
        return False
    content = (
        f"<p><b>{html.escape(message)}</b></p>"
        f"<p>检查时间：{html.escape(utc_now().strftime('%Y-%m-%d %H:%M:%S UTC'))}</p>"
        "<p>请打开 GitHub Actions 查看 tracker 和 watchdog 工作流。</p>"
    )
    results = send_to_all(tokens, title, content, topic=os.getenv("PUSHPLUS_TOPIC", "").strip())
    return bool(results) and all(results.values())


def run(
    *,
    heartbeat_file: Path,
    state_file: Path,
    stale_after_seconds: int,
    now: datetime | None = None,
) -> int:
    current = now or utc_now()
    heartbeat = load_json(heartbeat_file, {})
    problem = evaluate_heartbeat(
        heartbeat,
        now=current,
        stale_after_seconds=stale_after_seconds,
    )
    state = load_json(
        state_file,
        {"version": 1, "alert_active": False, "alert_kind": ""},
    )
    was_active = bool(state.get("alert_active"))
    old_kind = str(state.get("alert_kind", ""))

    if problem is not None:
        kind, message = problem
        if not was_active or old_kind != kind:
            ok = _notify("⚠️海外大V跟踪器报警", message)
            if not ok:
                return 2
            state.update(
                {
                    "version": 1,
                    "alert_active": True,
                    "alert_kind": kind,
                    "alerted_at": current.isoformat().replace("+00:00", "Z"),
                    "message": message,
                }
            )
            state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            LOG.error("watchdog alert sent: %s", message)
        else:
            LOG.error("watchdog problem remains active: %s", message)
        return 0

    if was_active:
        if not _notify("✅海外大V跟踪器已恢复", "跟踪器心跳已经恢复，监控任务目前正常运行。"):
            return 2
        state.update(
            {
                "version": 1,
                "alert_active": False,
                "alert_kind": "",
                "recovered_at": current.isoformat().replace("+00:00", "Z"),
            }
        )
        state.pop("message", None)
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        LOG.info("watchdog recovery notification sent")
    else:
        LOG.info("watchdog healthy")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Alert when the tracker heartbeat is stale")
    parser.add_argument("--heartbeat-file", default=os.getenv("HEARTBEAT_FILE", "monitor_heartbeat.json"))
    parser.add_argument("--state-file", default=os.getenv("WATCHDOG_STATE_FILE", "watchdog_state.json"))
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=int(os.getenv("HEARTBEAT_STALE_SECONDS", "900")),
    )
    args = parser.parse_args()
    return run(
        heartbeat_file=Path(args.heartbeat_file),
        state_file=Path(args.state_file),
        stale_after_seconds=max(60, args.stale_after_seconds),
    )


if __name__ == "__main__":
    raise SystemExit(main())
