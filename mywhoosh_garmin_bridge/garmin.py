"""Garmin Connect client: cached-token login, activity listing, FIT upload."""

import logging
from datetime import date, timedelta

from garminconnect import Garmin

logger = logging.getLogger(__name__)

ACTIVITY_TYPE_CYCLING = "cycling"


class GarminClient:
    def __init__(self, email: str, password: str, token_store: str, prompt_mfa=None):
        self._client = Garmin(
            email=email,
            password=password,
            prompt_mfa=prompt_mfa,
            return_on_mfa=True,
        )
        self._token_store = token_store

    def login(self) -> None:
        status, _state = self._client.login(self._token_store)
        if status == "needs_mfa":
            raise RuntimeError(
                "Garmin login requires MFA. Run once interactively with "
                "GARMIN_MFA_PROMPT=1 so the code can be entered, or pre-seed "
                "the token store."
            )

    def get_activities_by_date(self, startdate: date, enddate: date) -> list[dict]:
        return self._client.get_activities_by_date(
            startdate.isoformat(),
            enddate.isoformat(),
            activitytype=ACTIVITY_TYPE_CYCLING,
        )

    def upload_fit(self, fit_bytes: bytes, filename: str) -> dict:
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".fit", prefix="mywhoosh_")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(fit_bytes)
            return self._client.upload_activity(path)
        finally:
            os.unlink(path)


def activity_matches(
    garmin_activity: dict,
    start_ms: int,
    duration_s: float,
    tolerance_s: float = 300.0,
) -> bool:
    """True if a Garmin activity starts within tolerance of the indoor ride."""
    from datetime import datetime, timezone

    raw = garmin_activity.get("startTimeGMT") or garmin_activity.get("startTimeLocal")
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    garmin_start_ms = int(dt.timestamp() * 1000)
    return abs(garmin_start_ms - start_ms) <= tolerance_s * 1000


def find_existing_ride(
    activities: list[dict], start_ms: int, duration_s: float
) -> dict | None:
    for act in activities:
        if activity_matches(act, start_ms, duration_s):
            return act
    return None
