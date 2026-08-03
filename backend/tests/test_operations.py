import json
import logging

from app.operations import PrivacySafeJsonFormatter


def test_structured_logs_redact_sensitive_route_and_authentication_fields() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "route event", (), None)
    record.job_id = "job-1"
    record.stage = "osrm"
    record.password = "secret"
    record.token = "jwt"
    record.coordinates = [34.8, 32.0]
    record.origin_latitude = 32.0
    record.destination_longitude = 34.8
    record.address = "1 Sensitive Street"

    payload = json.loads(PrivacySafeJsonFormatter().format(record))

    assert payload["job_id"] == "job-1"
    assert payload["stage"] == "osrm"
    for field in ("password", "token", "coordinates", "origin_latitude", "destination_longitude", "address"):
        assert payload[field] == "[redacted]"
