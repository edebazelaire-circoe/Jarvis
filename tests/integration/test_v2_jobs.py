from __future__ import annotations

import asyncio

import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import Job, JobStatus, NotificationState


class FakeWorker:
    async def execute(self, job: Job) -> dict[str, object]:
        await asyncio.sleep(0)
        return {"processed": job.payload.get("value")}

    async def cancel(self, job_id: str) -> None:
        del job_id


@pytest.mark.asyncio
async def test_background_job_finishes_and_notifies_with_no_voice_runtime(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path, workers={"demo": FakeWorker()})
    await core.start()
    try:
        job = Job(kind="demo", payload={"value": 42})
        await core.jobs.submit(job)
        completed = ()
        delivered = ()
        for _ in range(100):
            completed = await core.state.list_jobs(status=JobStatus.COMPLETED.value)
            delivered = await core.state.list_notifications(state=NotificationState.DELIVERED.value)
            if completed and delivered:
                break
            await asyncio.sleep(0.01)
        assert completed and completed[0].result == {"processed": 42}
        assert delivered and delivered[0].originating_reference_id == job.id
    finally:
        await core.stop()
