"""Tests for the backend, driven entirely through its HTTP API.

This is one of the project's two agreed test seams. Everything behind the API —
ingestion, the Amplification Model, the Decision Model, the store — is internal and
may be restructured freely. A test that reaches past the API and asserts on internals
would defeat the point of choosing this seam.

No test here contacts a third-party service; conftest.py enforces that.
"""

from fastapi.testclient import TestClient

from nazarenow.api import DEVELOPMENT_ORIGINS, app

client = TestClient(app)


def test_placeholder_conditions_are_marked_as_not_real() -> None:
    """Nothing real is wired up yet, and the API must not pretend otherwise.

    The walking skeleton exists to prove the plumbing. A placeholder that looked like
    a genuine reading would be the exact failure this project most needs to avoid —
    output that appears successful and is wrong.
    """
    response = client.get("/api/conditions/current")

    assert response.status_code == 200
    body = response.json()
    assert body["placeholder"] is True
    assert body["location"] == "Praia do Norte, Nazare"
    assert body["message"]


def test_browser_requests_from_the_development_frontend_are_allowed() -> None:
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


def test_requests_from_an_unknown_origin_are_not_granted_access() -> None:
    response = client.get(
        "/api/conditions/current", headers={"Origin": "https://somewhere-else.example"}
    )

    assert "access-control-allow-origin" not in response.headers
