import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from mywhoosh_garmin_bridge import fit as fit_mod
from mywhoosh_garmin_bridge.config import Config
from mywhoosh_garmin_bridge.garmin import activity_matches, find_existing_ride
from mywhoosh_garmin_bridge.state import State
from mywhoosh_garmin_bridge.sync import sync
from tests.conftest import BASE_MS, build_trainer_fit

TODAY = date.today()
RIDE_DATE = TODAY - timedelta(days=1)
RIDE_START_LOCAL = datetime.fromtimestamp(BASE_MS / 1000, tz=timezone.utc).replace(tzinfo=None)
RIDE_DATE = RIDE_START_LOCAL.date()


def make_config(tmp_path, dry_run=True):
    return Config(
        icu_api_key="test-key",
        icu_athlete_id="0",
        garmin_email="test@example.com",
        garmin_password="secret",
        data_dir=tmp_path,
        lookback_days=7,
        dry_run=dry_run,
    )


class FakeIcu:
    def __init__(self, activities, files):
        self.activities = activities
        self.files = files
        self.downloads = []

    def list_activities(self, oldest, newest):
        return self.activities

    def download_file(self, activity_id):
        self.downloads.append(activity_id)
        data = self.files[activity_id]
        if isinstance(data, Exception):
            raise data
        return data

    def download_generated_fit(self, activity_id):
        self.downloads.append(("fit-file", activity_id))
        data = self.files[activity_id]
        if isinstance(data, Exception):
            raise data
        return data


class FakeGarmin:
    def __init__(self, activities_by_date=None):
        self.activities_by_date = activities_by_date or {}
        self.uploads = []
        self.logged_in = False

    def login(self):
        self.logged_in = True

    def get_activities_by_date(self, startdate, enddate):
        return self.activities_by_date.get(startdate, [])

    def upload_fit(self, fit_bytes, filename):
        self.uploads.append((fit_bytes, filename))
        return {"detailedImportResult": {"successes": [{"internalId": 555}]}}


def make_activity(id="i123", name="MyWhoosh ride", type="Ride", start=None):
    start = start or RIDE_DATE.isoformat()
    return SimpleNamespace(
        id=id,
        name=name,
        type=type,
        start_date_local=RIDE_START_LOCAL.isoformat(),
        file_type="fit",
    )


def test_sync_dry_run_uploads_nothing_to_garmin(tmp_path):
    config = make_config(tmp_path, dry_run=True)
    icu = FakeIcu([make_activity()], {"i123": build_trainer_fit()})
    garmin = FakeGarmin()

    result = sync(config, icu=icu, garmin=garmin)

    assert result.checked == 1
    assert result.uploaded == 1
    assert result.failed == 0
    assert garmin.uploads == []
    assert garmin.logged_in is False


def test_sync_marks_processed_and_skips_on_rerun(tmp_path):
    config = make_config(tmp_path, dry_run=True)
    icu = FakeIcu([make_activity()], {"i123": build_trainer_fit()})
    garmin = FakeGarmin()

    sync(config, icu=icu, garmin=garmin)
    result2 = sync(config, icu=icu, garmin=garmin)

    assert result2.checked == 1
    assert result2.skipped_already_synced == 1
    assert result2.uploaded == 0


def test_sync_skips_garmin_device_rides(tmp_path):
    config = make_config(tmp_path, dry_run=True)
    from fit_tool.profile.profile_type import Manufacturer, GarminProduct
    from tests.conftest import build_garmin_fit

    icu = FakeIcu([make_activity()], {"i123": build_garmin_fit()})
    garmin = FakeGarmin()

    result = sync(config, icu=icu, garmin=garmin)

    assert result.skipped_not_indoor == 1
    assert result.uploaded == 0


def test_sync_skips_rides_without_power(tmp_path):
    config = make_config(tmp_path, dry_run=True)
    icu = FakeIcu([make_activity()], {"i123": build_trainer_fit(with_power=False)})
    garmin = FakeGarmin()

    result = sync(config, icu=icu, garmin=garmin)

    assert result.skipped_not_indoor == 1
    assert result.uploaded == 0


def test_sync_skips_non_ride_types(tmp_path):
    config = make_config(tmp_path, dry_run=True)
    icu = FakeIcu([make_activity(type="Run")], {"i123": build_trainer_fit()})
    garmin = FakeGarmin()

    result = sync(config, icu=icu, garmin=garmin)

    assert result.skipped_not_indoor == 1
    assert result.uploaded == 0
    assert icu.downloads == []


def test_sync_real_upload_and_dedupe(tmp_path):
    config = make_config(tmp_path, dry_run=False)
    icu = FakeIcu([make_activity()], {"i123": build_trainer_fit()})
    garmin = FakeGarmin()

    result = sync(config, icu=icu, garmin=garmin)

    assert result.uploaded == 1
    assert garmin.logged_in is True
    assert len(garmin.uploads) == 1
    fit_bytes, filename = garmin.uploads[0]
    assert filename.endswith(".fit")
    # uploaded file must be a valid Edge 840 FIT
    info = fit_mod.inspect_fit(fit_bytes)
    assert fit_mod.is_indoor_ride.__name__ == "is_indoor_ride"
    from fit_tool.fit_file import FitFile
    from fit_tool.profile.profile_type import Manufacturer, GarminProduct

    fit = FitFile.from_bytes(fit_bytes)
    fid = next(r.message for r in fit.records if not r.is_definition and r.message.NAME == "file_id")
    assert fid.manufacturer == Manufacturer.GARMIN.value
    assert fid.product == GarminProduct.EDGE_840.value

    state = State(config.state_path)
    assert state.is_processed("i123")


def test_sync_dedupes_against_existing_garmin_ride(tmp_path):
    config = make_config(tmp_path, dry_run=False)
    icu = FakeIcu([make_activity()], {"i123": build_trainer_fit()})
    existing = {
        "activityId": 987654,
        "startTimeGMT": RIDE_START_LOCAL.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "activityType": {"typeKey": "cycling"},
    }
    garmin = FakeGarmin(activities_by_date={RIDE_DATE: [existing], RIDE_DATE - timedelta(days=1): [existing], RIDE_DATE + timedelta(days=1): [existing]})

    result = sync(config, icu=icu, garmin=garmin)

    assert result.skipped_already_on_garmin == 1
    assert result.uploaded == 0
    assert garmin.uploads == []
    state = State(config.state_path)
    assert state.is_processed("i123")


def test_sync_falls_back_to_generated_fit(tmp_path):
    config = make_config(tmp_path, dry_run=True)
    import requests

    icu = FakeIcu(
        [make_activity()],
        {"i123": requests.HTTPError("403 forbidden")},
    )
    # make generated fit available
    icu.files["i123"] = build_trainer_fit()
    garmin = FakeGarmin()

    # first download_file raises, then download_generated_fit returns bytes
    calls = {"n": 0}
    original_download = icu.download_file

    def flaky_download(activity_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.HTTPError("403 forbidden")
        return build_trainer_fit()

    icu.download_file = flaky_download
    icu.download_generated_fit = lambda activity_id: build_trainer_fit()

    result = sync(config, icu=icu, garmin=garmin)
    assert result.uploaded == 1
    assert result.failed == 0


def test_sync_counts_failures(tmp_path):
    config = make_config(tmp_path, dry_run=True)
    icu = FakeIcu([make_activity()], {"i123": b"not a fit file"})
    garmin = FakeGarmin()

    result = sync(config, icu=icu, garmin=garmin)
    assert result.failed == 1
    assert result.uploaded == 0


def test_activity_matches_tolerance():
    act = {"startTimeGMT": "2025-01-15T10:40:00"}
    assert activity_matches(act, BASE_MS, 600.0)
    assert not activity_matches(act, BASE_MS + 600 * 1000, 600.0)


def test_activity_matches_handles_z_suffix():
    act = {"startTimeGMT": "2025-01-15T10:40:00Z"}
    assert activity_matches(act, BASE_MS, 600.0)


def test_find_existing_ride():
    acts = [
        {"activityId": 1, "startTimeGMT": "2025-01-15T08:00:00"},
        {"activityId": 2, "startTimeGMT": "2025-01-15T10:40:00"},
    ]
    found = find_existing_ride(acts, BASE_MS, 600.0)
    assert found is not None
    assert found["activityId"] == 2


def test_state_roundtrip(tmp_path):
    state = State(tmp_path / "state.json")
    assert not state.is_processed("i1")
    state.mark_processed("i1", "garmin-1")
    state2 = State(tmp_path / "state.json")
    assert state2.is_processed("i1")
    data = json.loads((tmp_path / "state.json").read_text())
    assert data["processed"]["i1"]["garmin_activity_id"] == "garmin-1"


def test_state_corrupt_file_starts_fresh(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    state = State(path)
    assert not state.is_processed("i1")
