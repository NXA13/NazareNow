"""API-level behaviour that is not about a particular endpoint's payload.

Conditions ingestion and serving are covered in test_conditions.py, at the same seam.
"""

from fastapi.testclient import TestClient

from nazarenow.api import DEVELOPMENT_ORIGINS


def test_browser_requests_from_the_development_frontend_are_allowed(client: TestClient) -> None:
    """The frontend's origin must be permitted, or the app breaks only in a browser.

    This guards a defect that actually occurred: Vite silently moved to a different
    port when its default was occupied, leaving the running app on an origin this list
    did not allow. Neither test suite could see it, because both mock the boundary
    between frontend and backend — it surfaced only as a console error.
    """
    origin = "http://localhost:5273"
    assert origin in DEVELOPMENT_ORIGINS, "the pinned frontend origin must be allowed"

    response = client.get("/api/conditions/current", headers={"Origin": origin})

    assert response.headers["access-control-allow-origin"] == origin


def test_requests_from_an_unknown_origin_are_not_granted_access(client: TestClient) -> None:
    response = client.get(
        "/api/conditions/current", headers={"Origin": "https://somewhere-else.example"}
    )

    assert "access-control-allow-origin" not in response.headers
