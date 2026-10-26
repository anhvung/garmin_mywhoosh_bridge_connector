"""Small JSON state file tracking which intervals.icu activities were synced."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class State:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict = {"processed": {}}
        if path.exists():
            try:
                self._data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read state file %s (%s); starting fresh", path, exc)
                self._data = {"processed": {}}
        self._data.setdefault("processed", {})

    def is_processed(self, activity_id: str) -> bool:
        return activity_id in self._data["processed"]

    def mark_processed(self, activity_id: str, garmin_activity_id: str | None) -> None:
        self._data["processed"][activity_id] = {
            "garmin_activity_id": garmin_activity_id,
        }
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
        tmp.replace(self.path)
