import gzip

import pytest
from fit_tool.fit_file import FitFile
from fit_tool.profile.profile_type import FileType, GarminProduct, Manufacturer, Sport, SubSport

from mywhoosh_garmin_bridge import fit as fit_mod
from mywhoosh_garmin_bridge.fit import (
    GARMIN_EDGE_840,
    GARMIN_MANUFACTURER,
    inspect_fit,
    is_indoor_ride,
    rewrite_and_validate,
    rewrite_as_edge_840,
    to_gzip,
)
from tests.conftest import BASE_MS, build_trainer_fit


def _data_messages(fit):
    return [r.message for r in fit.records if not r.is_definition]


def test_inspect_trainer_fit(trainer_fit):
    info = inspect_fit(trainer_fit)
    assert info.manufacturer == Manufacturer.ZWIFT.value
    assert info.has_power
    assert info.has_heart_rate
    assert info.has_cadence
    assert info.record_count == 600
    assert info.start_ms == BASE_MS
    assert info.duration_s == pytest.approx(599.0)
    assert info.avg_power == pytest.approx(224.5)
    assert info.max_power == 249
    assert info.normalized_power is not None
    assert info.avg_heart_rate == pytest.approx(134.5)
    assert info.total_distance_m == pytest.approx(600 * 8.5)
    assert info.has_session and info.has_lap and info.has_activity


def test_inspect_garmin_fit_not_indoor(garmin_fit):
    info = inspect_fit(garmin_fit)
    assert info.manufacturer == GARMIN_MANUFACTURER
    assert not is_indoor_ride(info)


def test_is_indoor_ride_requires_power():
    fit_bytes = build_trainer_fit(with_power=False)
    info = inspect_fit(fit_bytes)
    assert info.has_heart_rate
    assert not info.has_power
    assert not is_indoor_ride(info)


def test_rewrite_changes_identity(trainer_fit):
    out = rewrite_as_edge_840(trainer_fit, serial_number=123456789)
    fit = FitFile.from_bytes(out)
    msgs = _data_messages(fit)

    fid = next(m for m in msgs if m.NAME == "file_id")
    assert fid.type == FileType.ACTIVITY.value
    assert fid.manufacturer == GARMIN_MANUFACTURER
    assert fid.product == GARMIN_EDGE_840
    assert fid.garmin_product == GARMIN_EDGE_840
    assert fid.serial_number == 123456789
    assert fid.time_created == BASE_MS

    devs = [m for m in msgs if m.NAME == "device_info"]
    assert len(devs) == 1
    dev = devs[0]
    assert dev.manufacturer == GARMIN_MANUFACTURER
    assert dev.product == GARMIN_EDGE_840
    assert dev.garmin_product == GARMIN_EDGE_840
    assert dev.serial_number == 123456789
    assert dev.device_type == 25
    assert dev.source_type == 5


def test_rewrite_keeps_record_stream(trainer_fit):
    out = rewrite_as_edge_840(trainer_fit, serial_number=1)
    fit = FitFile.from_bytes(out)
    records = [m for m in _data_messages(fit) if m.NAME == "record"]
    assert len(records) == 600
    first = records[0]
    assert first.timestamp == BASE_MS
    assert first.heart_rate == 120
    assert first.power == 200
    assert first.cadence == 85
    last = records[-1]
    assert last.timestamp == BASE_MS + 599 * 1000


def test_rewrite_session_stats(trainer_fit):
    out = rewrite_as_edge_840(trainer_fit, serial_number=1)
    fit = FitFile.from_bytes(out)
    sess = next(m for m in _data_messages(fit) if m.NAME == "session")
    assert sess.sport == Sport.CYCLING.value
    assert sess.sub_sport == SubSport.GENERIC.value
    assert sess.start_time == BASE_MS
    assert sess.timestamp == BASE_MS + 599 * 1000
    assert sess.total_timer_time == pytest.approx(599.0)
    assert sess.avg_power == 224
    assert sess.max_power == 249
    assert sess.normalized_power == 226
    assert sess.avg_heart_rate == 134
    assert sess.max_heart_rate == 149
    assert sess.avg_cadence == 90
    assert sess.total_calories == 500
    assert sess.total_ascent == 300
    assert sess.total_distance == pytest.approx(600 * 8.5)


def test_rewrite_adds_missing_device_and_activity():
    fit_bytes = build_trainer_fit(with_device_info=False, with_session=False, with_activity=False)
    out = rewrite_and_validate(fit_bytes, serial_number=42)
    fit = FitFile.from_bytes(out)
    msgs = _data_messages(fit)
    names = {m.NAME for m in msgs}
    assert "device_info" in names
    assert "session" in names
    assert "activity" in names
    dev = next(m for m in msgs if m.NAME == "device_info")
    assert dev.product == GARMIN_EDGE_840
    act = next(m for m in msgs if m.NAME == "activity")
    assert act.num_sessions == 1


def test_rewrite_and_validate_passes(trainer_fit):
    out = rewrite_and_validate(trainer_fit, serial_number=7)
    check = FitFile.from_bytes(out)
    errors = [f for f in check.validate().findings if f.severity.name == "ERROR"]
    assert errors == []


def test_rewrite_output_is_deterministic(trainer_fit):
    a = rewrite_as_edge_840(trainer_fit, serial_number=99)
    b = rewrite_as_edge_840(trainer_fit, serial_number=99)
    assert a == b


def test_to_gzip_roundtrip(trainer_fit):
    gz = to_gzip(trainer_fit)
    assert gz[:2] == b"\x1f\x8b"
    assert gzip.decompress(gz) == trainer_fit


def test_rewrite_requires_timestamps():
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.file_id_message import FileIdMessage

    builder = FitFileBuilder()
    fid = FileIdMessage()
    fid.type = FileType.ACTIVITY
    fid.manufacturer = Manufacturer.ZWIFT
    fid.product = 1
    fid.time_created = BASE_MS
    builder.add(fid)
    data = builder.build().to_bytes()
    with pytest.raises(ValueError, match="no record timestamps"):
        rewrite_as_edge_840(data, serial_number=1)


def test_rewrite_requires_file_id():
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.record_message import RecordMessage

    builder = FitFileBuilder()
    r = RecordMessage()
    r.timestamp = BASE_MS
    r.power = 200
    builder.add(r)
    data = builder.build().to_bytes()
    with pytest.raises(ValueError, match="no file_id"):
        rewrite_as_edge_840(data, serial_number=1)
