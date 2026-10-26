"""Rewrite a trainer FIT file so it looks like it was recorded on a Garmin Edge 840.

Garmin Connect computes Firstbeat metrics (Training Status, Training Load,
Training Effect) server-side from uploaded FIT activities, but only trusts
files that claim to come from a capable Garmin device and carry heart-rate
(and ideally power) time series. Trainer apps such as MyWhoosh write FIT
files whose file_id/device_info identify the app, so we patch those messages
in place, add the device identity, and keep the original record stream.
"""

import io
import logging
from dataclasses import dataclass

from fit_tool.definition_message import DefinitionMessage
from fit_tool.fit_file import FitFile
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.file_creator_message import FileCreatorMessage
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
from fit_tool.record import Record

logger = logging.getLogger(__name__)

GARMIN_MANUFACTURER = Manufacturer.GARMIN.value
GARMIN_EDGE_840 = GarminProduct.EDGE_840.value
EDGE_840_SOFTWARE_VERSION = 20.10
EDGE_840_HARDWARE_VERSION = 1.0
BIKE_COMPUTER_DEVICE_TYPE = 25

# MyWhoosh indoor rides arrive via Zwift-compatible uploads; both map to the
# same "not a Garmin device computer" bucket, so any non-Garmin manufacturer
# counts as an indoor ride.


@dataclass
class FitInfo:
    manufacturer: int | None
    product: int | None
    has_power: bool
    has_heart_rate: bool
    has_cadence: bool
    record_count: int
    start_ms: int | None
    end_ms: int | None
    duration_s: float
    avg_power: float | None
    max_power: int | None
    normalized_power: float | None
    avg_heart_rate: float | None
    max_heart_rate: int | None
    avg_cadence: float | None
    max_cadence: int | None
    total_distance_m: float | None
    total_ascent_m: float | None
    total_descent_m: float | None
    avg_speed: float | None
    max_speed: float | None
    avg_altitude: float | None
    max_altitude: float | None
    total_calories: int | None
    has_session: bool
    has_lap: bool
    has_activity: bool


def _messages(fit: FitFile):
    return (rec.message for rec in fit.records if not rec.is_definition)


def inspect_fit(data: bytes) -> FitInfo:
    fit = FitFile.from_bytes(data)
    records = [m for m in _messages(fit) if m.NAME == "record"]

    powers, heart_rates, cadences, speeds, altitudes = [], [], [], [], []
    timestamps = []
    for m in records:
        if m.timestamp is not None:
            timestamps.append(m.timestamp)
        if m.power is not None:
            powers.append(m.power)
        if m.heart_rate is not None:
            heart_rates.append(m.heart_rate)
        if m.cadence is not None:
            cadences.append(m.cadence)
        speed = m.enhanced_speed if m.enhanced_speed is not None else m.speed
        if speed is not None:
            speeds.append(speed)
        altitude = (
            m.enhanced_altitude if m.enhanced_altitude is not None else m.altitude
        )
        if altitude is not None:
            altitudes.append(altitude)

    manufacturer = product = None
    for m in _messages(fit):
        if m.NAME == "file_id":
            manufacturer = m.manufacturer
            product = m.product
            break

    names = {m.NAME for m in _messages(fit)}
    session = next((m for m in _messages(fit) if m.NAME == "session"), None)

    start_ms = min(timestamps) if timestamps else None
    end_ms = max(timestamps) if timestamps else None
    duration_s = (end_ms - start_ms) / 1000 if start_ms and end_ms else 0.0

    return FitInfo(
        manufacturer=manufacturer,
        product=product,
        has_power=bool(powers),
        has_heart_rate=bool(heart_rates),
        has_cadence=bool(cadences),
        record_count=len(records),
        start_ms=start_ms,
        end_ms=end_ms,
        duration_s=duration_s,
        avg_power=sum(powers) / len(powers) if powers else None,
        max_power=max(powers) if powers else None,
        normalized_power=_normalized_power(powers),
        avg_heart_rate=sum(heart_rates) / len(heart_rates) if heart_rates else None,
        max_heart_rate=max(heart_rates) if heart_rates else None,
        avg_cadence=sum(cadences) / len(cadences) if cadences else None,
        max_cadence=max(cadences) if cadences else None,
        total_distance_m=session.total_distance if session else None,
        total_ascent_m=session.total_ascent if session else None,
        total_descent_m=session.total_descent if session else None,
        avg_speed=sum(speeds) / len(speeds) if speeds else None,
        max_speed=max(speeds) if speeds else None,
        avg_altitude=sum(altitudes) / len(altitudes) if altitudes else None,
        max_altitude=max(altitudes) if altitudes else None,
        total_calories=session.total_calories if session else None,
        has_session="session" in names,
        has_lap="lap" in names,
        has_activity="activity" in names,
    )


def _normalized_power(powers: list[int]) -> float | None:
    """30-second rolling average of the 4th power of each sample (NP)."""
    if len(powers) < 30:
        return None
    window = 30
    rolling = []
    total = 0
    for i, p in enumerate(powers):
        total += p**4
        if i >= window:
            total -= powers[i - window] ** 4
        if i >= window - 1:
            rolling.append(total / window)
    return (sum(rolling) / len(rolling)) ** 0.25 if rolling else None


def is_indoor_ride(info: FitInfo) -> bool:
    """A ride with power data recorded by a non-Garmin device is an indoor ride."""
    return info.has_power and info.manufacturer != GARMIN_MANUFACTURER


def rewrite_as_edge_840(data: bytes, serial_number: int) -> bytes:
    """Patch a trainer FIT so Garmin Connect treats it as an Edge 840 recording.

    Keeps the original record stream (HR, power, cadence, speed, altitude)
    and rewrites the device identity, timer events, lap/session/activity
    summaries. Returns the new FIT bytes with a valid CRC.
    """
    fit = FitFile.from_bytes(data)
    info = inspect_fit(data)

    start_ms = info.start_ms
    if start_ms is None:
        raise ValueError("FIT file has no record timestamps; cannot rewrite")
    end_ms = info.end_ms or start_ms

    seen_file_id = seen_device = seen_session = seen_activity = False
    for rec in fit.records:
        if rec.is_definition:
            continue
        m = rec.message
        if m.NAME == "file_id":
            m.type = FileType.ACTIVITY
            m.manufacturer = Manufacturer.GARMIN
            m.product = GarminProduct.EDGE_840
            m.serial_number = serial_number
            m.time_created = start_ms
            seen_file_id = True
        elif m.NAME == "device_info":
            m.manufacturer = Manufacturer.GARMIN
            m.product = GarminProduct.EDGE_840
            m.serial_number = serial_number
            m.device_type = BIKE_COMPUTER_DEVICE_TYPE
            m.source_type = SourceType.LOCAL
            _set_if_present(m, "software_version", EDGE_840_SOFTWARE_VERSION)
            _set_if_present(m, "hardware_version", EDGE_840_HARDWARE_VERSION)
            seen_device = True
        elif m.NAME == "session":
            _rewrite_session(m, info, start_ms, end_ms)
            seen_session = True
        elif m.NAME == "activity":
            m.timestamp = end_ms
            m.total_timer_time = info.duration_s
            m.num_sessions = 1
            m.type = Activity.MANUAL
            m.event = Event.ACTIVITY
            m.event_type = EventType.STOP_DISABLE
            seen_activity = True

    if not seen_file_id:
        raise ValueError("FIT file has no file_id message; cannot rewrite")

    extras = []
    if not seen_device:
        extras.append(_device_info_message(start_ms, serial_number))
    if not seen_session:
        extras.append(_session_message(info, start_ms, end_ms))
    if not seen_activity:
        extras.append(_activity_message(end_ms, info.duration_s))

    if extras:
        for msg in extras:
            fit.add_record(Record.from_message(DefinitionMessage.from_data_message(msg)))
            fit.add_record(Record.from_message(msg))

    return fit.to_bytes()


def _set_if_present(message, attr: str, value) -> None:
    """Set a message attribute only when the source file actually carries the field.

    Decoded messages have fixed-size, non-growable fields; writing a field the
    original definition did not include would raise FitEncodingError. A field
    that exists but was left empty by the recorder is treated as absent: we
    only fill in summaries, never invent structure the file doesn't declare.
    """
    field = message.get_field_by_name(attr)
    if field is not None and field.is_valid():
        setattr(message, attr, value)


def _rewrite_session(m: SessionMessage, info: FitInfo, start_ms: int, end_ms: int) -> None:
    m.sport = Sport.CYCLING
    m.sub_sport = SubSport.GENERIC
    m.timestamp = end_ms
    m.start_time = start_ms
    m.total_elapsed_time = info.duration_s
    m.total_timer_time = info.duration_s
    m.total_distance = info.total_distance_m or 0.0
    if info.avg_power is not None:
        _set_if_present(m, "avg_power", round(info.avg_power))
    if info.max_power is not None:
        _set_if_present(m, "max_power", info.max_power)
    if info.normalized_power is not None:
        _set_if_present(m, "normalized_power", round(info.normalized_power))
    if info.avg_heart_rate is not None:
        _set_if_present(m, "avg_heart_rate", round(info.avg_heart_rate))
    if info.max_heart_rate is not None:
        _set_if_present(m, "max_heart_rate", info.max_heart_rate)
    if info.avg_cadence is not None:
        _set_if_present(m, "avg_cadence", round(info.avg_cadence))
    if info.max_cadence is not None:
        _set_if_present(m, "max_cadence", info.max_cadence)
    if info.total_calories is not None:
        _set_if_present(m, "total_calories", info.total_calories)
    if info.total_ascent_m is not None:
        _set_if_present(m, "total_ascent", round(info.total_ascent_m))
    if info.total_descent_m is not None:
        _set_if_present(m, "total_descent", round(info.total_descent_m))
    if info.avg_speed is not None:
        _set_if_present(m, "enhanced_avg_speed", info.avg_speed)
    if info.max_speed is not None:
        _set_if_present(m, "enhanced_max_speed", info.max_speed)
    if info.avg_altitude is not None:
        _set_if_present(m, "enhanced_avg_altitude", info.avg_altitude)
    if info.max_altitude is not None:
        _set_if_present(m, "enhanced_max_altitude", info.max_altitude)
    m.event = Event.LAP
    m.event_type = EventType.STOP_DISABLE


def _device_info_message(start_ms: int, serial_number: int) -> DeviceInfoMessage:
    m = DeviceInfoMessage()
    m.timestamp = start_ms
    m.device_index = 0
    m.device_type = BIKE_COMPUTER_DEVICE_TYPE
    m.manufacturer = Manufacturer.GARMIN
    m.serial_number = serial_number
    m.product = GarminProduct.EDGE_840
    m.software_version = EDGE_840_SOFTWARE_VERSION
    m.hardware_version = EDGE_840_HARDWARE_VERSION
    m.source_type = SourceType.LOCAL
    return m


def _session_message(info: FitInfo, start_ms: int, end_ms: int) -> SessionMessage:
    m = SessionMessage()
    m.message_index = 0
    m.first_lap_index = 0
    m.num_laps = 1
    _rewrite_session(m, info, start_ms, end_ms)
    return m


def _activity_message(end_ms: int, duration_s: float) -> ActivityMessage:
    m = ActivityMessage()
    m.timestamp = end_ms
    m.total_timer_time = duration_s
    m.num_sessions = 1
    m.type = Activity.MANUAL
    m.event = Event.ACTIVITY
    m.event_type = EventType.STOP_DISABLE
    return m


def to_gzip(data: bytes) -> bytes:
    import gzip

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(data)
    return buf.getvalue()


def rewrite_and_validate(data: bytes, serial_number: int) -> bytes:
    """Rewrite the FIT and verify the result parses with a valid CRC."""
    out = rewrite_as_edge_840(data, serial_number)
    check = FitFile.from_bytes(out)
    report = check.validate()
    errors = [f for f in report.findings if f.severity.name == "ERROR"]
    if errors:
        raise ValueError(f"Rewritten FIT failed validation: {errors}")
    fid = next(m for m in _messages(check) if m.NAME == "file_id")
    if fid.manufacturer != GARMIN_MANUFACTURER or fid.product != GARMIN_EDGE_840:
        raise ValueError("Rewritten FIT does not carry the Edge 840 identity")
    return out


__all__ = [
    "FitInfo",
    "inspect_fit",
    "is_indoor_ride",
    "rewrite_as_edge_840",
    "rewrite_and_validate",
    "to_gzip",
    "GARMIN_EDGE_840",
    "GARMIN_MANUFACTURER",
]
