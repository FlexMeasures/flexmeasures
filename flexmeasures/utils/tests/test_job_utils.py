from __future__ import annotations

from datetime import timedelta
import logging

from rq import Queue
from rq.job import Job

from flexmeasures.app import create as create_app
from flexmeasures.tests.utils import RQCompatibleFakeStrictRedis
from flexmeasures.utils.job_utils import get_job_timeout


def test_get_job_timeout_uses_default_timeout():
    config = {
        "FLEXMEASURES_DEFAULT_JOB_TIMEOUT": "PT5M",
        "FLEXMEASURES_JOB_TIMEOUT": {},
    }

    assert get_job_timeout("scheduling", config) == 300


def test_get_job_timeout_uses_queue_specific_timeout():
    config = {
        "FLEXMEASURES_DEFAULT_JOB_TIMEOUT": "PT5M",
        "FLEXMEASURES_JOB_TIMEOUT": {"forecasting": "PT1H"},
    }

    assert get_job_timeout("forecasting", config) == 3600
    assert get_job_timeout("scheduling", config) == 300


def test_get_job_timeout_accepts_timedelta_values():
    assert (
        get_job_timeout(
            "scheduling",
            {
                "FLEXMEASURES_DEFAULT_JOB_TIMEOUT": timedelta(minutes=5),
                "FLEXMEASURES_JOB_TIMEOUT": {"scheduling": timedelta(minutes=10)},
            },
        )
        == 600
    )


def test_get_job_timeout_falls_back_on_numeric_seconds(caplog):
    with caplog.at_level(logging.ERROR):
        timeout = get_job_timeout(
            "scheduling",
            {
                "FLEXMEASURES_DEFAULT_JOB_TIMEOUT": "PT5M",
                "FLEXMEASURES_JOB_TIMEOUT": {"scheduling": 45},
            },
        )

    assert timeout == 300
    assert "Invalid FLEXMEASURES_JOB_TIMEOUT for queue 'scheduling'" in caplog.text


def test_get_job_timeout_falls_back_on_nominal_default_duration(caplog):
    with caplog.at_level(logging.ERROR):
        timeout = get_job_timeout(
            "scheduling",
            {
                "FLEXMEASURES_DEFAULT_JOB_TIMEOUT": "P1M",
                "FLEXMEASURES_JOB_TIMEOUT": {},
            },
        )

    assert timeout == 180
    assert "Invalid FLEXMEASURES_DEFAULT_JOB_TIMEOUT" in caplog.text


def test_get_job_timeout_falls_back_on_non_mapping_queue_timeouts(caplog):
    with caplog.at_level(logging.ERROR):
        timeout = get_job_timeout(
            "scheduling",
            {
                "FLEXMEASURES_DEFAULT_JOB_TIMEOUT": "PT5M",
                "FLEXMEASURES_JOB_TIMEOUT": ["scheduling"],
            },
        )

    assert timeout == 300
    assert "Invalid FLEXMEASURES_JOB_TIMEOUT" in caplog.text


def test_get_job_timeout_logs_unknown_queue_names(caplog):
    with caplog.at_level(logging.ERROR):
        timeout = get_job_timeout(
            "forecasting",
            {
                "FLEXMEASURES_DEFAULT_JOB_TIMEOUT": "PT5M",
                "FLEXMEASURES_JOB_TIMEOUT": {"forecast": "PT1H"},
            },
        )

    assert timeout == 300
    assert "Invalid FLEXMEASURES_JOB_TIMEOUT queue names ['forecast']" in caplog.text


def test_queue_default_timeout_is_used_for_enqueued_jobs():
    queue = Queue(
        name="scheduling",
        connection=RQCompatibleFakeStrictRedis(),
        default_timeout=get_job_timeout(
            "scheduling",
            {
                "FLEXMEASURES_DEFAULT_JOB_TIMEOUT": "PT5M",
                "FLEXMEASURES_JOB_TIMEOUT": {},
            },
        ),
    )

    job = queue.enqueue(sum, [1, 2])

    assert queue._default_timeout == 300
    assert job.timeout == 300


def test_queue_default_timeout_is_used_when_enqueueing_created_jobs():
    queue = Queue(
        name="scheduling",
        connection=RQCompatibleFakeStrictRedis(),
        default_timeout=300,
    )
    job = Job.create(sum, args=([1, 2],), connection=queue.connection)

    assert job.timeout is None

    queue.enqueue_job(job)

    assert job.timeout == 300


def test_app_queues_use_default_job_timeout(app):
    assert app.queues["forecasting"]._default_timeout == 180
    assert app.queues["scheduling"]._default_timeout == 180
    assert app.queues["ingestion"]._default_timeout == 180


def test_app_queues_use_custom_global_and_queue_job_timeout(tmp_path, monkeypatch):
    import flexmeasures.ui

    monkeypatch.setattr(flexmeasures.ui, "register_at", lambda app: None)
    config_file = tmp_path / "flexmeasures.cfg"
    config_file.write_text(
        "\n".join(
            [
                'SECRET_KEY = "dummy-key-for-job-timeout-test"',
                'SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"',
                "SQLALCHEMY_ENGINE_OPTIONS = {}",
                'FLEXMEASURES_DEFAULT_JOB_TIMEOUT = "PT5M"',
                'FLEXMEASURES_JOB_TIMEOUT = {"forecasting": "PT1H"}',
                "FLEXMEASURES_PROFILE_REQUESTS = False",
                "FLEXMEASURES_CREATE_TEMPLATE_ASSETS_ON_STARTUP = False",
            ]
        ),
        encoding="utf-8",
    )

    custom_app = create_app(env="development", path_to_config=str(config_file))

    assert custom_app.queues["forecasting"]._default_timeout == 3600
    assert custom_app.queues["scheduling"]._default_timeout == 300
    assert custom_app.queues["ingestion"]._default_timeout == 300
