"""Adding a field to a stored call must not be able to half-happen.

Ticket #67. #15 added five columns to `day_call`, and each was named by hand in the DDL, the
column list, the migration, the insert, the row mapper, the API model and the frontend. Nine
places for one logical change, which is Shotgun Surgery — but the cost is not the typing.

**The cost is that one of the nine fails silently.** A field left out of the row mapper reads
back as absent, and every consumer already treats absence as "an older call, from before this
field existed". So a dropped field renders as a call that predates the feature: no exception,
no empty value, no wrong number — a plausible, ordinary-looking answer. That is this
project's characteristic failure and the one it keeps having to design against.

These tests pin the two directions drift can go now that the store has a single declaration:
a column the table has and the declaration does not, and a column the declaration has and the
table does not.
"""

from __future__ import annotations

import sqlite3

import pytest

from nazarenow.store import CALL_COLUMN_NAMES, CALL_FIELDS, Store, StoreUnavailable


class TestTheDeclarationAndTheTableAgree:
    def test_every_declared_column_exists_in_the_table(self, store) -> None:
        """The declaration drives the reads, so a column it names and the table lacks is a
        failure at the first request rather than at construction — which is the
        bare-500-without-CORS outcome eager verification exists to prevent."""
        actual = {
            row["name"]
            for row in store._connect().execute("PRAGMA table_info(day_call)")  # noqa: SLF001
        }

        assert set(CALL_COLUMN_NAMES) <= actual, (
            f"declared but not in the table: {sorted(set(CALL_COLUMN_NAMES) - actual)}"
        )

    def test_every_stored_column_is_declared(self, store) -> None:
        """The direction that fails silently, and the reason this test exists.

        A column added to the DDL and forgotten in the declaration is never selected, never
        mapped, and reads back as absent — indistinguishable from a call written before the
        column existed. Nothing raises and nothing looks wrong.
        """
        actual = {
            row["name"]
            for row in store._connect().execute("PRAGMA table_info(day_call)")  # noqa: SLF001
        }
        # `id` is the store's own key and `run_id` is provenance carried separately by
        # `call_history`; neither is part of a call's payload.
        payload = actual - {"id", "run_id"}

        assert payload <= set(CALL_COLUMN_NAMES), (
            f"stored but never read back: {sorted(payload - set(CALL_COLUMN_NAMES))}"
        )

    def test_a_store_missing_a_declared_column_refuses_to_open(self, tmp_path) -> None:
        """Verified eagerly, not on the first request.

        A database carrying the right tables with the wrong columns used to pass construction
        and fail inside an endpoint. This is that same guarantee, now covering whatever the
        declaration grows to rather than a hand-maintained list of probes.
        """
        path = tmp_path / "shortened.db"
        writer = Store(path)
        writer.close()

        connection = sqlite3.connect(path)
        connection.execute("ALTER TABLE day_call DROP COLUMN height_bar_probability")
        connection.commit()
        connection.close()

        with pytest.raises(StoreUnavailable, match="height_bar_probability"):
            Store(path, create=False)


class TestARoundTripKeepsEveryField:
    def test_every_declared_field_survives_being_written_and_read(self, store) -> None:
        """One assertion per field, generated from the declaration itself.

        Written this way rather than as a list of named fields, because a hand-written list
        is the ninth site all over again: it would need editing for the next field, and
        forgetting it would leave the new field untested while the suite stayed green.
        """
        stored = {
            "date": "2026-02-13",
            "issued_for_date": "2026-02-09",
            "status": "go",
            "lead_time_days": 4,
            "reasons": ["a reason"],
            "predicted_significant_wave_height": 6.1,
            "unit": "m",
            "amplification_model": "learned-amplification",
            "calibrated": True,
            "calibration": {"fitted_at": "2026-08-08"},
            "model_agreement": "agreed",
            "go_call_withheld": False,
            "plausible_range_m": (5.2, 7.0),
            "height_bar_probability": 0.82,
            "uncertainty_measured": True,
            "go_call_withheld_for_uncertainty": False,
        }
        run_id = store.begin_run()
        store.record_run(
            observed_at="2026-02-09T00:00",
            latitude=39.56,
            longitude=-9.21,
            readings={},
            hours=[],
            model_hours=[],
            calls=[stored],
            spreads=[],
            run_id=run_id,
        )

        read_back = store.call_history()[0]

        for field in CALL_FIELDS:
            if field.key is None:
                continue
            assert field.key in read_back, f"{field.key} was written and never read back"
            if field.key == "issued_at":
                # The one field the call does not supply: it is the run's own stamp, so the
                # fixture has nothing to compare against. That it arrives at all is the
                # property worth pinning.
                assert read_back["issued_at"], "the run stamped nothing onto its calls"
                continue
            assert read_back[field.key] == stored[field.key], f"{field.key} did not survive"

    def test_the_declaration_covers_what_a_decided_call_carries(self) -> None:
        """The declaration is checked against `Call`, not against a copy of its field list.

        This is the seam the nine sites ran through: a field added to the decision layer and
        forgotten in the store is a field the record silently never keeps.
        """
        from dataclasses import fields as dataclass_fields

        from nazarenow.decision import Call

        declared = {field.key for field in CALL_FIELDS if field.key is not None}
        # `status` and `reasons` are on `Call`; `date`, `issued_at` and the model's identity
        # are added by the pipeline around it, so the store knows more than `Call` does.
        decided = {field.name for field in dataclass_fields(Call)}

        assert decided <= declared, (
            f"a decided call carries fields the store never stores: {sorted(decided - declared)}"
        )
