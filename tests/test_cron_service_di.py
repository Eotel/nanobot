import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore


def _build_job(
    *,
    job_id: str = "job-1",
    name: str = "job",
    enabled: bool = True,
    schedule: CronSchedule | None = None,
    delete_after_run: bool = False,
) -> CronJob:
    return CronJob(
        id=job_id,
        name=name,
        enabled=enabled,
        schedule=schedule or CronSchedule(kind="every", every_ms=60_000),
        payload=CronPayload(kind="agent_turn", message="hello"),
        state=CronJobState(next_run_at_ms=1_000),
        created_at_ms=100,
        updated_at_ms=100,
        delete_after_run=delete_after_run,
    )


def test_constructor_injection(tmp_path: Path) -> None:
    store_path = tmp_path / "cron.json"
    callback = AsyncMock()

    service = CronService(store_path=store_path, on_job=callback)

    assert service.store_path == store_path
    assert service.on_job is callback
    assert service._store is None
    assert service._timer_task is None
    assert service._running is False


async def test_store_path_usage_on_startup(tmp_path: Path, monkeypatch) -> None:
    now_ms = 1_700_000_000_000
    store_path = tmp_path / "seeded-cron.json"
    store_path.write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": [
                    {
                        "id": "seed1",
                        "name": "seeded job",
                        "enabled": True,
                        "schedule": {"kind": "every", "everyMs": 60_000},
                        "payload": {"kind": "agent_turn", "message": "run"},
                        "state": {},
                        "createdAtMs": now_ms - 1000,
                        "updatedAtMs": now_ms - 1000,
                        "deleteAfterRun": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    service = CronService(store_path=store_path)
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now_ms)
    arm_timer = MagicMock()
    monkeypatch.setattr(service, "_arm_timer", arm_timer)

    await service.start()

    assert service._store is not None
    assert len(service._store.jobs) == 1
    job = service._store.jobs[0]
    assert job.id == "seed1"
    assert job.name == "seeded job"
    assert job.state.next_run_at_ms == now_ms + 60_000
    arm_timer.assert_called_once_with()


async def test_optional_on_job_default_none(tmp_path: Path, monkeypatch) -> None:
    now_ms = 1_000
    service = CronService(store_path=tmp_path / "cron.json")
    job = _build_job(job_id="no-callback")
    service._store = CronStore(jobs=[job])
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now_ms)

    await service._execute_job(job)

    assert job.state.last_status == "ok"
    assert job.state.last_error is None
    assert job.state.last_run_at_ms == now_ms


async def test_callback_injection_success(tmp_path: Path, monkeypatch) -> None:
    now_ms = 2_000
    callback = AsyncMock(return_value="done")
    service = CronService(store_path=tmp_path / "cron.json", on_job=callback)
    job = _build_job(job_id="ok-callback")
    service._store = CronStore(jobs=[job])
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now_ms)

    await service._execute_job(job)

    callback.assert_awaited_once_with(job)
    assert job.state.last_status == "ok"
    assert job.state.last_error is None


async def test_callback_injection_error(tmp_path: Path, monkeypatch) -> None:
    now_ms = 3_000
    callback = AsyncMock(side_effect=RuntimeError("boom"))
    service = CronService(store_path=tmp_path / "cron.json", on_job=callback)
    job = _build_job(job_id="error-callback")
    service._store = CronStore(jobs=[job])
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now_ms)

    await service._execute_job(job)

    callback.assert_awaited_once_with(job)
    assert job.state.last_status == "error"
    assert job.state.last_error == "boom"


async def test_one_shot_delete_after_run(tmp_path: Path, monkeypatch) -> None:
    now_ms = 4_000
    service = CronService(store_path=tmp_path / "cron.json")
    job = _build_job(
        job_id="oneshot-delete",
        schedule=CronSchedule(kind="at", at_ms=now_ms + 1_000),
        delete_after_run=True,
    )
    service._store = CronStore(jobs=[job])
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now_ms)

    await service._execute_job(job)

    assert service._store.jobs == []


async def test_one_shot_disable_after_run(tmp_path: Path, monkeypatch) -> None:
    now_ms = 5_000
    service = CronService(store_path=tmp_path / "cron.json")
    job = _build_job(
        job_id="oneshot-disable",
        schedule=CronSchedule(kind="at", at_ms=now_ms + 1_000),
        delete_after_run=False,
    )
    service._store = CronStore(jobs=[job])
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now_ms)

    await service._execute_job(job)

    assert service._store.jobs == [job]
    assert job.enabled is False
    assert job.state.next_run_at_ms is None


async def test_run_job_with_force_flag(tmp_path: Path, monkeypatch) -> None:
    now_ms = 6_000
    callback = AsyncMock(return_value=None)
    service = CronService(store_path=tmp_path / "cron.json", on_job=callback)
    job = _build_job(job_id="manual-run", enabled=False)
    service._store = CronStore(jobs=[job])
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now_ms)
    save_store = MagicMock()
    arm_timer = MagicMock()
    monkeypatch.setattr(service, "_save_store", save_store)
    monkeypatch.setattr(service, "_arm_timer", arm_timer)

    assert await service.run_job(job.id) is False
    callback.assert_not_awaited()
    save_store.assert_not_called()
    arm_timer.assert_not_called()

    assert await service.run_job(job.id, force=True) is True
    callback.assert_awaited_once_with(job)
    save_store.assert_called_once_with()
    arm_timer.assert_called_once_with()


def test_persistence_triggers_save(tmp_path: Path, monkeypatch) -> None:
    now_ms = 7_000
    service = CronService(store_path=tmp_path / "cron.json")
    service._store = CronStore()
    save_store = MagicMock()
    arm_timer = MagicMock()
    monkeypatch.setattr(service, "_save_store", save_store)
    monkeypatch.setattr(service, "_arm_timer", arm_timer)
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now_ms)

    job = service.add_job(
        name="persist",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    save_store.assert_called_once_with()
    arm_timer.assert_called_once_with()

    save_store.reset_mock()
    arm_timer.reset_mock()
    updated = service.enable_job(job.id, enabled=False)
    assert updated is not None
    save_store.assert_called_once_with()
    arm_timer.assert_called_once_with()

    save_store.reset_mock()
    arm_timer.reset_mock()
    assert service.remove_job(job.id) is True
    save_store.assert_called_once_with()
    arm_timer.assert_called_once_with()


def test_invalid_store_fallback(tmp_path: Path) -> None:
    store_path = tmp_path / "broken-cron.json"
    store_path.write_text("{not-json}", encoding="utf-8")

    service = CronService(store_path=store_path)
    store = service._load_store()

    assert isinstance(store, CronStore)
    assert store.jobs == []
