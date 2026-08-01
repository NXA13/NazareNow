"""What happened to a Pipeline Run, in the vocabulary the store records it in.

Separate from `store` because these are domain facts rather than persistence: how a run
ended, and what kind of thing went wrong. Separate from `pipeline` because the scheduler
and anything later reading the record need the vocabulary without importing the network
call behind it.
"""

from __future__ import annotations

from enum import StrEnum


class RunOutcome(StrEnum):
    """How a Pipeline Run ended.

    `RUNNING` is not a placeholder for "we forgot to update it". A run is marked started
    before it does anything, and only the run itself can mark it finished — so a record
    left at `RUNNING` is how a host that died mid-run makes itself visible afterwards.
    No `except` clause can write that, because the process was not there to run one.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FailureKind(StrEnum):
    """What sort of thing went wrong, for whoever reads the record months later.

    "Failed" alone cannot tell a provider having a bad afternoon from a payload this
    system has stopped understanding, and those call for opposite responses: the first is
    waited out, the second means the parser is now wrong about the world and every run
    until someone fixes it will fail the same way. A season of runs marked only "failed"
    would need the detail strings re-read by hand to tell which had happened.

    `UNEXPECTED` is deliberate rather than a gap. The scheduler survives what nobody
    anticipated by design, so the record has to be able to say "this was not one of the
    three things we knew about" instead of forcing a wrong label onto it.
    """

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PAYLOAD_UNRECOGNISED = "payload_unrecognised"
    STORE_UNAVAILABLE = "store_unavailable"
    UNEXPECTED = "unexpected"
