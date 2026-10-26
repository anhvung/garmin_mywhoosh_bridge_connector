import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    icu_api_key: str
    icu_athlete_id: str
    garmin_email: str
    garmin_password: str
    data_dir: Path
    lookback_days: int
    dry_run: bool

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Config":
        env = os.environ if env is None else env
        missing = [
            key
            for key in ("ICU_API_KEY", "GARMIN_EMAIL", "GARMIN_PASSWORD")
            if not env.get(key)
        ]
        if missing:
            raise ValueError(
                "Missing required environment variables: " + ", ".join(missing)
            )
        data_dir = Path(env.get("BRIDGE_DATA_DIR", ".data"))
        return cls(
            icu_api_key=env["ICU_API_KEY"],
            icu_athlete_id=env.get("ICU_ATHLETE_ID", "0"),
            garmin_email=env["GARMIN_EMAIL"],
            garmin_password=env["GARMIN_PASSWORD"],
            data_dir=data_dir,
            lookback_days=int(env.get("BRIDGE_LOOKBACK_DAYS", "7")),
            dry_run=env.get("BRIDGE_DRY_RUN", "0") == "1",
        )

    @property
    def token_store(self) -> str:
        return str(self.data_dir / "garmin_tokens.json")

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"
