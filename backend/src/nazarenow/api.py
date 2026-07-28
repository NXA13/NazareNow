"""The read-only HTTP API.

Per ADR 0005 this layer only ever reads. It evaluates no model and contacts no
third-party service — a Pipeline Run does that on a schedule and writes its results to
a store, which this API serves. Nothing here should ever grow a network call outward.

Right now there is no store and no pipeline, so the one endpoint returns a placeholder
that says so.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="NazareNow",
    description="Forecasts when Praia do Norte will produce giant waves.",
    version="0.1.0",
)

# Must match the port pinned in frontend/vite.config.ts. If the two drift apart the app
# fails only in a browser, with a CORS error neither test suite can see, because both
# seams mock the boundary between them. A test asserts this list to stop that recurring.
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


class CurrentConditions(BaseModel):
    """What the API reports for Praia do Norte right now.

    Declared as a model rather than a loose dict so FastAPI's generated schema is the
    single description of this shape — the frontend, the tests and the docs all
    disagreeing about it is a problem worth designing out early.
    """

    placeholder: bool
    """True while the API serves stand-in values rather than measurements."""

    location: str
    message: str


@app.get("/api/conditions/current")
def current_conditions() -> CurrentConditions:
    """A placeholder standing in for what a Pipeline Run will eventually store.

    Deliberately carries `placeholder: true` rather than plausible-looking numbers.
    The frontend surfaces that flag, so nobody can mistake the walking skeleton for a
    working forecast.
    """
    return CurrentConditions(
        placeholder=True,
        location="Praia do Norte, Nazare",
        message="Wired end to end. No conditions are being measured yet.",
    )
