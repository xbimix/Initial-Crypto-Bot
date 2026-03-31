from __future__ import annotations

from runtime import periodic


class _Logger:
    def __init__(self):
        self.info_messages: list[str] = []
        self.warning_messages: list[str] = []

    def info(self, message: str):
        self.info_messages.append(str(message))

    def warning(self, message: str):
        self.warning_messages.append(str(message))


def test_run_account_sync_if_due_runs_and_updates_timestamp():
    logger = _Logger()
    calls = {"count": 0}

    def _sync():
        calls["count"] += 1
        return {"sync_status": "ok", "asset_count": 3}

    updated = periodic.run_account_sync_if_due(
        now_epoch=100.0,
        last_run_at=0.0,
        interval_seconds=10.0,
        sync_fn=_sync,
        logger=logger,
    )
    assert updated == 100.0
    assert calls["count"] == 1
    assert logger.info_messages


def test_run_account_sync_if_due_skips_when_not_due():
    logger = _Logger()
    calls = {"count": 0}

    def _sync():
        calls["count"] += 1
        return {}

    updated = periodic.run_account_sync_if_due(
        now_epoch=15.0,
        last_run_at=10.0,
        interval_seconds=10.0,
        sync_fn=_sync,
        logger=logger,
    )
    assert updated == 10.0
    assert calls["count"] == 0


def test_run_db_maintenance_if_due_handles_errors():
    logger = _Logger()

    def _maintenance():
        raise RuntimeError("boom")

    updated = periodic.run_db_maintenance_if_due(
        now_epoch=200.0,
        last_run_at=0.0,
        interval_seconds=5.0,
        maintenance_fn=_maintenance,
        logger=logger,
    )
    assert updated == 200.0
    assert logger.warning_messages


def test_log_heartbeat_if_due():
    logger = _Logger()
    skipped = periodic.log_heartbeat_if_due(
        now_epoch=20.0,
        last_heartbeat_at=15.0,
        heartbeat_interval_seconds=10.0,
        logger=logger,
    )
    assert skipped == 15.0

    emitted = periodic.log_heartbeat_if_due(
        now_epoch=40.0,
        last_heartbeat_at=15.0,
        heartbeat_interval_seconds=10.0,
        logger=logger,
    )
    assert emitted == 40.0
    assert any("Heartbeat" in msg for msg in logger.info_messages)
