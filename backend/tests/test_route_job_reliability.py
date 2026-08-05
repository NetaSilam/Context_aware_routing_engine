from app.routing.route_job_tasks import celery_app


def test_celery_route_delivery_has_bounded_recovery_configuration() -> None:
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.worker_pool == "prefork"
    assert celery_app.conf.worker_concurrency >= 1
    assert celery_app.conf.task_soft_time_limit > 0
    assert celery_app.conf.task_time_limit > celery_app.conf.task_soft_time_limit
    visibility_timeout = celery_app.conf.broker_transport_options["visibility_timeout"]
    assert celery_app.conf.task_time_limit < visibility_timeout
