"""Live cron sync: map source_job_ids to ~/.hermes/cron/jobs.json.

Read-only mapping of schedule, state, last status and next run. Tests use a
fixture jobs.json, never the real one.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from agent_context import cron_sync, store, ws


def write_jobs(rows, updated_at="2026-11-25T14:00:00+07:00"):
    path = os.path.join(tempfile.mkdtemp(), "jobs.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"jobs": rows, "updated_at": updated_at}, f)
    return path


def job(job_id="j1", name="alpha", enabled=True, state="scheduled",
        display="every day at 8am", last_run_at="2026-11-25T08:00:00+07:00",
        last_status="ok", next_run_at="2026-11-26T08:00:00+07:00",
        last_error=None, no_agent=True):
    return {"id": job_id, "name": name, "enabled": enabled, "state": state,
            "no_agent": no_agent, "schedule_display": display,
            "schedule": {"kind": "cron", "expr": "0 8 * * *",
                         "display": display},
            "last_run_at": last_run_at, "last_status": last_status,
            "next_run_at": next_run_at, "last_error": last_error}


def fresh():
    return store.connect(":memory:")


class CronLoad(unittest.TestCase):
    def test_missing_file_is_empty(self):
        snap = cron_sync.load("/nonexistent/jobs.json")
        self.assertEqual(snap["jobs"], {})

    def test_malformed_file_is_empty(self):
        path = os.path.join(tempfile.mkdtemp(), "jobs.json")
        with open(path, "w") as f:
            f.write("{not json")
        self.assertEqual(cron_sync.load(path)["jobs"], {})

    def test_maps_jobs_and_parses_times(self):
        path = write_jobs([job()])
        snap = cron_sync.load(path)
        rec = snap["jobs"]["j1"]
        self.assertEqual(rec["name"], "alpha")
        self.assertEqual(rec["schedule"], "every day at 8am")
        self.assertTrue(rec["enabled"])
        self.assertEqual(rec["last_status"], "ok")
        self.assertIsNotNone(rec["last_run_ts"])
        self.assertGreater(rec["next_run_ts"], rec["last_run_ts"])
        self.assertEqual(snap["updated_at"], "2026-11-25T14:00:00+07:00")

    def test_long_error_is_truncated(self):
        path = write_jobs([job(last_status="error",
                               last_error="x" * 2000)])
        rec = cron_sync.load(path)["jobs"]["j1"]
        self.assertLessEqual(len(rec["last_error"]), cron_sync.MAX_ERROR)
        self.assertTrue(rec["last_error"].endswith("…"))

    def test_never_leaks_prompt(self):
        row = job()
        row["prompt"] = "a long system prompt"
        rec = cron_sync.load(write_jobs([row]))["jobs"]["j1"]
        self.assertNotIn("prompt", rec)


class CronSummarize(unittest.TestCase):
    def test_empty_ids_is_on_demand(self):
        out = cron_sync.summarize([])
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["schedule"], "on demand")
        self.assertIsNone(out["next_run_ts"])
        self.assertIsNone(out["last_status"])

    def test_all_missing_ids_are_flagged(self):
        snap = cron_sync.load(write_jobs([]))
        out = cron_sync.summarize(["nope"], snap)
        self.assertEqual(out["missing"], 1)
        self.assertEqual(out["jobs"][0]["id"], "nope")
        self.assertTrue(out["jobs"][0]["missing"])
        self.assertEqual(out["schedule"], "no cron job")

    def test_soonest_enabled_job_wins_next_run(self):
        snap = cron_sync.load(write_jobs([
            job("j1", "alpha", display="every day at 8am",
                next_run_at="2026-11-26T08:00:00+07:00"),
            job("j2", "beta", display="every 60m",
                next_run_at="2026-11-25T15:00:00+07:00"),
        ]))
        out = cron_sync.summarize(["j1", "j2"], snap)
        self.assertEqual(out["next_job_id"], "j2")
        self.assertEqual(out["schedule"], "every 60m +1")
        self.assertEqual(out["count"], 2)

    def test_paused_jobs_do_not_set_next_run(self):
        snap = cron_sync.load(write_jobs([
            job("j1", enabled=False, state="paused", next_run_at=None),
        ]))
        out = cron_sync.summarize(["j1"], snap)
        self.assertEqual(out["schedule"], "paused")
        self.assertIsNone(out["next_run_ts"])
        self.assertEqual(out["paused"], 1)

    def test_last_status_follows_most_recent_run(self):
        snap = cron_sync.load(write_jobs([
            job("j1", last_run_at="2026-11-25T08:00:00+07:00",
                last_status="error", last_error="boom"),
            job("j2", last_run_at="2026-11-25T13:00:00+07:00",
                last_status="ok"),
        ]))
        out = cron_sync.summarize(["j1", "j2"], snap)
        self.assertEqual(out["last_status"], "ok")
        self.assertEqual(out["jobs"][0]["last_status"], "error")

    def test_job_detail_has_no_prompt(self):
        snap = cron_sync.load(write_jobs([job()]))
        out = cron_sync.summarize(["j1"], snap)
        self.assertEqual(set(out["jobs"][0]),
                         {"id", "name", "schedule", "state", "enabled",
                          "no_agent", "last_status", "last_run_ts",
                          "next_run_ts", "last_error"})


class WsCronIntegration(unittest.TestCase):
    def setUp(self):
        self.con = fresh()
        ws.seed(self.con)
        self.path = write_jobs([
            job("2d5f972a5570", "health-ops 4am sweep",
                display="every day at 4am",
                last_run_at="2026-11-25T04:14:00+07:00",
                next_run_at="2026-11-26T04:00:00+07:00"),
            job("8dc816b7ce57", "daily-device-audit",
                display="every day at 8am",
                last_run_at="2026-11-25T08:00:00+07:00",
                next_run_at="2026-11-26T08:00:00+07:00"),
            job("99eb38de9bb7", "device-recon", display="every 60m",
                last_run_at="2026-11-25T14:00:00+07:00",
                next_run_at="2026-11-25T15:00:00+07:00"),
        ])

    def test_list_agents_carries_live_cron(self):
        agents = ws.list_agents(self.con, cron_path=self.path)
        a = next(x for x in agents if x["slug"] == "health-auditor")
        self.assertEqual(a["cron"]["count"], 5)
        self.assertEqual(a["cron"]["live"], 3)
        self.assertEqual(a["cron"]["missing"], 2)
        self.assertEqual(a["cron"]["next_job_id"], "99eb38de9bb7")
        self.assertTrue(a["cron"]["schedule"].startswith("every 60m"))
        b = next(x for x in agents if x["slug"] == "coach-builder")
        self.assertEqual(b["cron"]["count"], 0)
        self.assertEqual(b["cron"]["schedule"], "on demand")

    def test_get_agent_cron_detail(self):
        a = ws.get_agent(self.con, "health-auditor", cron_path=self.path)
        jobs = a["cron"]["jobs"]
        self.assertEqual(len(jobs), 5)
        live = next(j for j in jobs if j["id"] == "2d5f972a5570")
        self.assertEqual(live["schedule"], "every day at 4am")
        self.assertEqual(live["state"], "scheduled")
        missing = [j for j in jobs if j.get("missing")]
        self.assertEqual(len(missing), 2)

    def test_cron_error_marks_agent_error_when_newer(self):
        path = write_jobs([job("2d5f972a5570", last_status="error",
                               last_run_at="2026-11-25T12:00:00+07:00",
                               last_error="boom")])
        ws.record_run(self.con, "health-auditor", job_id="x", status="ok",
                      summary="old ok", started_at=1000.0, ended_at=1100.0)
        a = ws.get_agent(self.con, "health-auditor", cron_path=path)
        self.assertEqual(a["status"], "error")
        # A newer recorded run clears it.
        ws.record_run(self.con, "health-auditor", job_id="x", status="ok",
                      summary="new ok", started_at=9e9, ended_at=9e9 + 10)
        a = ws.get_agent(self.con, "health-auditor", cron_path=path)
        self.assertEqual(a["status"], "idle")

    def test_missing_cron_file_keeps_agents_working(self):
        agents = ws.list_agents(self.con, cron_path="/nonexistent/jobs.json")
        a = next(x for x in agents if x["slug"] == "health-auditor")
        self.assertEqual(a["cron"]["count"], 5)
        self.assertEqual(a["cron"]["live"], 0)
        self.assertEqual(a["cron"]["missing"], 5)

    def test_env_path_is_honoured(self):
        with mock.patch.dict(os.environ,
                             {"AGENT_MANAGER_CRON_JOBS": self.path}):
            agents = ws.list_agents(self.con)
        a = next(x for x in agents if x["slug"] == "health-auditor")
        self.assertEqual(a["cron"]["live"], 3)


class CronRoute(unittest.TestCase):
    def setUp(self):
        self.con = fresh()
        ws.seed(self.con)
        self.path = write_jobs([job("99eb38de9bb7", display="every 60m",
                                    next_run_at="2026-11-25T15:00:00+07:00")])

    def test_list_route_exposes_cron(self):
        from agent_context import ws_routes
        with mock.patch.dict(os.environ,
                             {"AGENT_MANAGER_CRON_JOBS": self.path}):
            code, body = ws_routes.get(self.con, "/api/ws/agents")
        self.assertEqual(code, 200)
        a = next(x for x in body["agents"] if x["slug"] == "health-auditor")
        self.assertEqual(a["cron"]["live"], 1)
        self.assertIsNotNone(a["cron"]["next_run_ts"])


if __name__ == "__main__":
    unittest.main()
