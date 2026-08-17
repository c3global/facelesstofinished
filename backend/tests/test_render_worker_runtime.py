import unittest

from render_worker_runtime import (
    terminal_exit_code,
    worker_claim_query,
    worker_claim_update,
    worker_interrupted_update,
)


class RenderWorkerRuntimeTests(unittest.TestCase):
    def test_claim_only_accepts_unclaimed_queued_job(self):
        query = worker_claim_query("job-123")
        self.assertEqual(query["id"], "job-123")
        self.assertEqual(query["status"], "queued")
        self.assertIn({"worker_execution_id": {"$exists": False}}, query["$or"])
        self.assertIn({"worker_execution_id": None}, query["$or"])

    def test_claim_stamps_backend_and_execution(self):
        update = worker_claim_update("exec-1", now_iso="2026-08-17T12:00:00+00:00")
        fields = update["$set"]
        self.assertEqual(fields["worker_backend"], "cloud_run_job")
        self.assertEqual(fields["worker_execution_id"], "exec-1")
        self.assertEqual(fields["updated_at"], "2026-08-17T12:00:00+00:00")

    def test_interruption_is_terminal_and_auditable(self):
        update = worker_interrupted_update(
            "exec-2", now_iso="2026-08-17T12:01:00+00:00",
        )
        fields = update["$set"]
        self.assertEqual(fields["status"], "failed")
        self.assertTrue(fields["worker_interrupted"])
        self.assertEqual(fields["completed_at"], fields["updated_at"])

    def test_only_complete_exits_successfully(self):
        self.assertEqual(terminal_exit_code("complete"), 0)
        self.assertEqual(terminal_exit_code("failed"), 1)
        self.assertEqual(terminal_exit_code(None), 1)


if __name__ == "__main__":
    unittest.main()
