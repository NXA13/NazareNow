"""Tests for the backend, driven entirely through its HTTP API.

This is one of the project's two agreed test seams. Everything behind the API —
ingestion, the Amplification Model, the Decision Model, the store — is internal and
may be restructured freely. A test that reaches past the API and asserts on internals
would defeat the point of choosing this seam.

No test here contacts a third-party service.
"""

from fastapi.testclient import TestClient

from nazarenow.api import app

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
    assert "Praia do Norte" in body["location"]


def test_unknown_paths_are_not_found() -> None:
    response = client.get("/api/nothing-here")

    assert response.status_code == 404
