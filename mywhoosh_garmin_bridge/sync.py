"""Sync orchestration: intervals.icu -> FIT rewrite -> Garmin Connect."""

import logging
import random
from dataclasses import dataclass
from datetime import date, timedelta

from . import fit as fit_mod
from .garmin import GarminClient, find_existing_ride
from .intervals import IntervalsClient
from .state import State

logger = logging.getLogger(__name__)

# Garmin dedupes uploads by (start time, duration) on their side too, but we
# check explicitly so we can skip cleanly and keep state accurate.
GARMIN_LOOKBACK_DAYS = 2
GARMIN_SERIAL_SALT = "mywhoosh-garmin-bridge"


@dataclass
class SyncResult:
    checked: int = 0
    uploaded: int = 0
    skipped_already_synced: int = 0
    skipped_not_indoor: int = 0
    skipped_already_on_garmin: int = 0
    skipped_no_power: int = 0
    failed: int = 0


def _serial_for(activity_id: str) -> int:
    """Stable pseudo device serial derived from the activity id (uint32 range)."""
    return (abs(hash(activity_id)) % (2**31 - 1)) + 1


def sync(config, icu: IntervalsClient | None = None, garmin: GarminClient | None = None) -> SyncResult:
    result = SyncResult()
    icu = icu or IntervalsClient(config.icu_api_key, config.icu_athlete_id)
    state = State(config.state_path)

    garmin = garmin or GarminClient(
        config.garmin_email, config.garmin_password, config.token_store
    )
    if not config.dry_run:
        garmin.login()

    today = date.today()
    oldest = today - timedelta(days=config.lookback_days)
    activities = icu.list_activities(oldest, today)
    logger.info("Found %d intervals.icu activities in the last %d days", len(activities), config.lookback_days)

    garmin_cache: dict[date, list[dict]] = {}

    for act in activities:
        result.checked += 1
        if state.is_processed(act.id):
            result.skipped_already_synced += 1
            continue
        if act.type.lower() not in ("ride", "virtualride", "virtual_ride"):
            result.skipped_not_indoor += 1
            continue

        try:
            fit_bytes = icu.download_file(act.id)
        except Exception:
            logger.exception("Failed to download %s (%s); trying regenerated FIT", act.id, act.name)
            try:
                fit_bytes = icu.download_generated_fit(act.id)
            except Exception:
                logger.exception("Failed to download regenerated FIT for %s", act.id)
                result.failed += 1
                continue

        try:
            info = fit_mod.inspect_fit(fit_bytes)
        except Exception:
            logger.exception("Could not parse FIT for %s (%s)", act.id, act.name)
            result.failed += 1
            continue

        if not fit_mod.is_indoor_ride(info):
            result.skipped_not_indoor += 1
            continue
        if not info.has_heart_rate:
            logger.warning(
                "Skipping %s (%s): indoor ride without heart rate data; "
                "Garmin cannot compute training metrics",
                act.id,
                act.name,
            )
            result.skipped_no_power += 1
            continue
        if info.start_ms is None or info.duration_s <= 0:
            logger.warning("Skipping %s (%s): no usable timestamps", act.id, act.name)
            result.failed += 1
            continue

        if not config.dry_run:
            day = date.fromisoformat(act.start_date_local[:10])
            if day not in garmin_cache:
                window_start = day - timedelta(days=1)
                window_end = day + timedelta(days=1)
                garmin_cache[day] = garmin.get_activities_by_date(window_start, window_end)
            # also check neighbouring days in cache lazily
            for offset in (-1, 0, 1):
                d = day + timedelta(days=offset)
                if d not in garmin_cache:
                    garmin_cache[d] = garmin.get_activities_by_date(
                        d - timedelta(days=1), d + timedelta(days=1)
                    )
            existing = find_existing_ride(
                [a for d in (day - timedelta(days=1), day, day + timedelta(days=1)) for a in garmin_cache[d]],
                info.start_ms,
                info.duration_s,
            )
            if existing is not None:
                logger.info(
                    "Skipping %s (%s): matching ride already on Garmin (activity %s)",
                    act.id,
                    act.name,
                    existing.get("activityId"),
                )
                state.mark_processed(act.id, str(existing.get("activityId")))
                result.skipped_already_on_garmin += 1
                continue

        serial = _serial_for(act.id)
        try:
            rewritten = fit_mod.rewrite_and_validate(fit_bytes, serial)
        except Exception:
            logger.exception("Failed to rewrite FIT for %s (%s)", act.id, act.name)
            result.failed += 1
            continue

        if config.dry_run:
            logger.info(
                "[dry-run] Would upload %s (%s): %.0fs, avg %.0fW, NP %.0fW, avg HR %.0f",
                act.id,
                act.name,
                info.duration_s,
                info.avg_power or 0,
                info.normalized_power or 0,
                info.avg_heart_rate or 0,
            )
            state.mark_processed(act.id, None)
            result.uploaded += 1
            continue

        filename = f"{act.start_date_local.replace(':', '-')}_{act.id}.fit"
        try:
            response = garmin.upload_fit(rewritten, filename)
        except Exception:
            logger.exception("Failed to upload %s (%s) to Garmin", act.id, act.name)
            result.failed += 1
            continue

        garmin_id = None
        if isinstance(response, dict):
            detail = response.get("detailedImportResult") or {}
            successes = detail.get("successes") or []
            if successes:
                garmin_id = str(successes[0].get("internalId") or successes[0].get("activityId"))
        logger.info("Uploaded %s (%s) to Garmin Connect (activity %s)", act.id, act.name, garmin_id)
        state.mark_processed(act.id, garmin_id)
        result.uploaded += 1

    logger.info(
        "Sync done: %d checked, %d uploaded, %d already synced, %d not indoor, "
        "%d already on Garmin, %d skipped (no HR), %d failed",
        result.checked,
        result.uploaded,
        result.skipped_already_synced,
        result.skipped_not_indoor,
        result.skipped_already_on_garmin,
        result.skipped_no_power,
        result.failed,
    )
    return result
