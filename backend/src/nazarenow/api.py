"""The read-only HTTP API.

Per ADR 0005 this layer only ever reads. It evaluates no model and contacts no
third-party service — a Pipeline Run does that on a schedule and writes its results to
a store, which this API serves. Nothing here should ever grow a network call outward.

Right now there is no store and no pipeline, so the one endpoint returns a placeholder
that says so.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="NazareNow",
    description="Forecasts when Praia do Norte will produce giant waves.",
    version="0.1.0",
)

# The frontend is served separately in development, so the browser treats it as a
# different origin. This list must match the port pinned in frontend/vite.config.ts —
# if they drift apart the app fails only in the browser, with a CORS error the test
# suites cannot catch, because both seams mock this boundary.
# Production origins get added when there is somewhere to deploy to.
DEVELOPMENT_ORIGINS = [
    "http://localhost:5273",
    "http://127.0.0.1:5273",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEVELOPMENT_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/conditions/current")
def current_conditions() -> dict[str, object]:
    """Placeholder standing in for the current Offshore Conditions.

    Deliberately carries `placeholder: true` rather than plausible-looking numbers.
    The frontend surfaces that flag, so nobody can mistake the walking skeleton for a
    working forecast.
    """
    return {
        "placeholder": True,
        "location": "Praia do Norte, Nazare",
        "message": "Wired end to end. No conditions are being measured yet.",
    }
