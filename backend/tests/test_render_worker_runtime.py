import unittest
from datetime import datetime, timezone

from render_execution import resolve_execution_backend, should_use_isolated_queue
from render_privacy import scrub_render_for_customer
from render_runtime import (
    lease_expiry_iso,
    queued_render_query,
    stale_render_query,
    worker_lock_query,
    worker_lock_update,
)
from render_worker_runtime import (
    terminal_exit_code,
    worker_claim_query,
    worker_claim_update,
    worker_interrupted_update,
)


class RenderWorkerRuntimeTests(unittest.TestCase):
    def test_owner_cutover_forces_cloud_run_queue(self):
        self.assertEqual(
            resolve_execution_backend("local", owner_cutover=True),
            "cloud_run_queue",
        )

    def test_platform_database_keeps_configured_backend(self):
        self.assertEqual(
            resolve_execution_backend("local", owner_cutover=False),
            "local",
        )

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

    def test_stale_reaper_excludes_jobs_that_have_not_started(self):
        query = stale_render_query("2026-08-17T12:00:00+00:00")
        self.assertEqual(
            query["status"],
            {"$nin": ["queued", "complete", "failed"]},
        )

    def test_queue_selects_only_unclaimed_faceless_jobs(self):
        self.assertEqual(queued_render_query(), {
            "status": "queued",
            "mode": {"$in": ["faceless"]},
            "$or": [
                {"worker_execution_id": {"$exists": False}},
                {"worker_execution_id": None},
            ],
        })

    def test_queue_lock_is_leased_and_renewable_by_its_owner(self):
        now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
        expiry = lease_expiry_iso(seconds=180, now=now)
        query = worker_lock_query("exec-1", now_iso=now.isoformat())
        update = worker_lock_update(
            "exec-1", lease_expires_at=expiry, now_iso=now.isoformat(),
        )
        self.assertEqual(query["_id"], "faceless48-render-queue")
        self.assertIn({"owner": "exec-1"}, query["$or"])
        self.assertEqual(update["$set"]["lease_expires_at"], expiry)

    def test_only_faceless_uses_isolated_queue_at_cutover(self):
        modes = {"faceless"}
        self.assertTrue(should_use_isolated_queue(
            backend="cloud_run_queue", isolated_modes=modes, mode="faceless",
        ))
        self.assertFalse(should_use_isolated_queue(
            backend="cloud_run_queue", isolated_modes=modes, mode="avatar",
        ))
        self.assertFalse(should_use_isolated_queue(
            backend="local", isolated_modes=modes, mode="faceless",
        ))

    def test_worker_identity_is_not_customer_facing(self):
        self.assertEqual(scrub_render_for_customer({
            "id": "job-1",
            "worker_backend": "cloud_run_job",
            "worker_execution_id": "exec-1",
            "worker_claimed_at": "now",
        }), {"id": "job-1"})


if __name__ == "__main__":
    unittest.main()
