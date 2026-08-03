import asyncio
import json

from app import health
from app.config import get_settings


def test_known_osrm_deployment_combination_is_ready(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"tested_combinations": [{"graph_version": "unit-test-graph-v1", "corridor_risk_version": "risk-v1", "matcher_version": "sampled-nearest-v1"}]}))
    monkeypatch.setenv("OSRM_DEPLOYMENT_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("OSRM_COMPATIBILITY_REQUIRED", "true")
    get_settings.cache_clear()
    assert asyncio.run(health._osrm_compatibility_readiness("risk-v1")) == {"status": "ready"}
    get_settings.cache_clear()


def test_unknown_osrm_deployment_combination_fails_readiness(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"tested_combinations": []}')
    monkeypatch.setenv("OSRM_DEPLOYMENT_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("OSRM_COMPATIBILITY_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        asyncio.run(health._osrm_compatibility_readiness("risk-v1"))
    except RuntimeError as error:
        assert "unverified" in str(error)
    else:
        raise AssertionError("unknown combination passed readiness")
    get_settings.cache_clear()
