"""Minimal intervals.icu API client (personal API key, basic auth)."""

import gzip
import logging
from dataclasses import dataclass
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://intervals.icu/api/v1"


@dataclass
class IcuActivity:
    id: str
    name: str
    type: str
    start_date_local: str
    file_type: str | None


class IntervalsClient:
    def __init__(self, api_key: str, athlete_id: str = "0", timeout: int = 30):
        self.athlete_id = athlete_id
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = ("API_KEY", api_key)
        self.session.headers.update({"Accept": "application/json"})

    def list_activities(self, oldest: date, newest: date) -> list[IcuActivity]:
        resp = self.session.get(
            f"{BASE_URL}/athlete/{self.athlete_id}/activities",
            params={
                "oldest": oldest.isoformat(),
                "newest": (newest + timedelta(days=1)).isoformat(),
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return [
            IcuActivity(
                id=str(a["id"]),
                name=a.get("name", ""),
                type=a.get("type", ""),
                start_date_local=a.get("start_date_local", ""),
                file_type=a.get("file_type"),
            )
            for a in resp.json()
        ]

    def download_file(self, activity_id: str) -> bytes:
        """Download the original activity file (FIT, possibly gzip-compressed)."""
        resp = self.session.get(
            f"{BASE_URL}/activity/{activity_id}/file",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.content
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data

    def download_generated_fit(self, activity_id: str) -> bytes:
        """Download intervals.icu's regenerated FIT (always FIT, gzipped)."""
        resp = self.session.get(
            f"{BASE_URL}/activity/{activity_id}/fit-file",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.content
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data
