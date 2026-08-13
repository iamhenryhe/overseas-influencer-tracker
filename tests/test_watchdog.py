import unittest
from datetime import datetime, timezone

from src.watchdog import evaluate_heartbeat


class WatchdogTests(unittest.TestCase):
    def test_missing_heartbeat_is_a_problem(self):
        result = evaluate_heartbeat({}, now=datetime.now(timezone.utc), stale_after_seconds=900)
        self.assertEqual(result[0], "missing")

    def test_fresh_healthy_heartbeat_is_ok(self):
        now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
        heartbeat = {"updated_at": "2026-08-13T07:58:00Z", "status": "ok", "exit_code": 0}
        self.assertIsNone(evaluate_heartbeat(heartbeat, now=now, stale_after_seconds=900))

    def test_stale_heartbeat_is_a_problem(self):
        now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
        heartbeat = {"updated_at": "2026-08-13T07:40:00Z", "status": "ok", "exit_code": 0}
        result = evaluate_heartbeat(heartbeat, now=now, stale_after_seconds=900)
        self.assertEqual(result[0], "stale")

    def test_failed_check_is_a_problem_even_with_fresh_heartbeat(self):
        now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
        heartbeat = {"updated_at": "2026-08-13T07:59:00Z", "status": "error", "exit_code": 1, "iteration": 5}
        result = evaluate_heartbeat(heartbeat, now=now, stale_after_seconds=900)
        self.assertEqual(result[0], "check_failed")


if __name__ == "__main__":
    unittest.main()
