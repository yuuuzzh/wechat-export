"""Tests for async backup job store + status API."""
from __future__ import annotations

import pytest

from web.job_store import JobStore, ProgressJob


def test_progress_job_never_blocks_when_subscriber_gone():
    job = ProgressJob('backup')
    q = job.subscribe(replay_logs=False)
    # Drain initial snapshot
    assert q.get_nowait()['status'] in ('pending', 'running')
    job.unsubscribe(q)

    # Flood progress with no live subscribers — must not hang.
    for i in range(300):
        job.progress_event('decrypt', f'step {i}', i / 300)
    assert job.status == 'running'
    assert job.progress > 0.9


def test_job_store_active_and_done():
    store = JobStore(keep=4)
    assert store.active() is None
    job = store.create('backup')
    job.progress_event('scan', 'hi', 0.1)
    assert store.active('backup') is job
    job.mark_done({'success': True})
    assert store.active('backup') is None
    assert store.current('backup') is job
    snap = job.snapshot()
    assert snap['status'] == 'done'
    assert snap['result']['success'] is True


def test_subscribe_after_done_gets_terminal_event():
    job = ProgressJob('backup')
    job.mark_done({'ok': 1})
    q = job.subscribe(replay_logs=False)
    item = q.get(timeout=1)
    assert item['stage'] == 'done'
    assert item['result']['ok'] == 1


def test_fanout_to_two_subscribers():
    job = ProgressJob('backup')
    a = job.subscribe(replay_logs=False)
    b = job.subscribe(replay_logs=False)
    # drain snapshots
    a.get_nowait()
    b.get_nowait()
    job.progress_event('migrate', 'copying', 0.5)
    ea = a.get(timeout=1)
    eb = b.get(timeout=1)
    assert ea['detail'] == 'copying'
    assert eb['progress'] == 0.5


def test_backup_job_status_api():
    """Flask status endpoint returns the in-memory job snapshot."""
    pytest.importorskip('flask')
    from web.app import create_app
    from web.job_store import backup_jobs

    app = create_app(decrypted_dir='')
    job = backup_jobs.create('backup')
    job.progress_event('index', 'building', 0.8)

    client = app.test_client()
    res = client.get('/api/backup/job')
    assert res.status_code == 200
    data = res.get_json()
    assert data['ok'] is True
    assert data['job']['id'] == job.id
    assert data['job']['status'] == 'running'
    assert data['job']['stage'] == 'index'
    assert data['job']['running'] is True

    res_one = client.get(f'/api/backup/job?id={job.id}')
    assert res_one.get_json()['job']['id'] == job.id

    job.mark_done({'success': True})
    done = client.get('/api/backup/job').get_json()['job']
    assert done['status'] == 'done'
    assert done['running'] is False