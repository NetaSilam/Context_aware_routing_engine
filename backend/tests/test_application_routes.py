from fastapi.testclient import TestClient

from app.main import create_app


def test_obsolete_synchronous_routing_endpoints_are_absent() -> None:
    with TestClient(create_app()) as client:
        route_response = client.post("/api/route", json={})
        geocode_response = client.get("/api/geocode", params={"q": "Tel Aviv"})

    assert route_response.status_code == 404
    assert geocode_response.status_code == 404


def test_preserved_api_boundaries_remain_registered() -> None:
    paths = {route.path for route in create_app().routes}

    assert "/api/auth/login" in paths
    assert "/api/route-history" in paths
    assert "/api/route-history/{job_id}" in paths
    assert "/api/geocoding/search" in paths
    assert "/api/canonical-network/corridors" in paths
    assert "/api/accident-attribution/accidents" in paths
