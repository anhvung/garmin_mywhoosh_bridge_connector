import pytest
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.profile_type import (
    Activity,
    Event,
    EventType,
    FileType,
    GarminProduct,
    Manufacturer,
    Sport,
    SourceType,
    SubSport,
)

BASE_MS = 1736937600000  # 2025-01-15T10:40:00Z


def build_trainer_fit(
    manufacturer=Manufacturer.ZWIFT,
    product=12345,
    seconds=600,
    with_power=True,
    with_hr=True,
    with_cadence=True,
    with_device_info=True,
    with_session=True,
    with_activity=True,
    with_lap=True,
) -> bytes:
    """Build a MyWhoosh/Zwift-style indoor trainer FIT."""
    builder = FitFileBuilder()

    fid = FileIdMessage()
    fid.type = FileType.ACTIVITY
    fid.manufacturer = manufacturer
    fid.product = product
    fid.serial_number = 424242
    fid.time_created = BASE_MS
    builder.add(fid)

    if with_device_info:
        dev = DeviceInfoMessage()
        dev.timestamp = BASE_MS
        dev.device_index = 0
        dev.device_type = 1
        dev.manufacturer = manufacturer
        dev.serial_number = 424242
        dev.product = 777
        dev.software_version = 4.5
        dev.source_type = SourceType.LOCAL
        builder.add(dev)

    distance = 0.0
    altitude = 100.0
    for i in range(seconds):
        r = RecordMessage()
        r.timestamp = BASE_MS + i * 1000
        if with_hr:
            r.heart_rate = 120 + (i % 30)
        if with_cadence:
            r.cadence = 85 + (i % 10)
        if with_power:
            r.power = 200 + (i % 50)
        r.enhanced_speed = 8.0 + (i % 5) * 0.1
        altitude += 0.5
        r.enhanced_altitude = altitude
        distance += 8.5
        r.distance = distance
        builder.add(r)

    if with_lap:
        lap = LapMessage()
        lap.message_index = 0
        lap.timestamp = BASE_MS + seconds * 1000
        lap.start_time = BASE_MS
        lap.total_elapsed_time = float(seconds)
        lap.total_timer_time = float(seconds)
        lap.total_distance = distance
        lap.event = Event.LAP
        lap.event_type = EventType.STOP_DISABLE
        builder.add(lap)

    if with_session:
        sess = SessionMessage()
        sess.message_index = 0
        sess.first_lap_index = 0
        sess.num_laps = 1
        sess.timestamp = BASE_MS + seconds * 1000
        sess.start_time = BASE_MS
        sess.sport = Sport.CYCLING
        sess.sub_sport = SubSport.GENERIC
        sess.total_elapsed_time = float(seconds)
        sess.total_timer_time = float(seconds)
        sess.total_distance = distance
        if with_power:
            sess.avg_power = 224
            sess.max_power = 249
            sess.normalized_power = 226
        if with_hr:
            sess.avg_heart_rate = 134
            sess.max_heart_rate = 149
        if with_cadence:
            sess.avg_cadence = 89
            sess.max_cadence = 94
        sess.total_ascent = 300
        sess.total_descent = 300
        sess.total_calories = 500
        sess.event = Event.LAP
        sess.event_type = EventType.STOP_DISABLE
        builder.add(sess)

    if with_activity:
        act = ActivityMessage()
        act.timestamp = BASE_MS + seconds * 1000
        act.total_timer_time = float(seconds)
        act.num_sessions = 1
        act.type = Activity.MANUAL
        act.event = Event.ACTIVITY
        act.event_type = EventType.STOP_DISABLE
        builder.add(act)

    return builder.build().to_bytes()


def build_garmin_fit(seconds=600) -> bytes:
    """Build a FIT that already claims to be from an Edge 840."""
    return build_trainer_fit(manufacturer=Manufacturer.GARMIN, product=GarminProduct.EDGE_840)


@pytest.fixture
def trainer_fit() -> bytes:
    return build_trainer_fit()


@pytest.fixture
def garmin_fit() -> bytes:
    return build_garmin_fit()
