import pytest

from mywhoosh_garmin_bridge.config import Config


def test_config_from_env(tmp_path):
    env = {
        "ICU_API_KEY": "key",
        "ICU_ATHLETE_ID": "42",
        "GARMIN_EMAIL": "a@b.c",
        "GARMIN_PASSWORD": "pw",
        "BRIDGE_DATA_DIR": str(tmp_path),
        "BRIDGE_LOOKBACK_DAYS": "14",
        "BRIDGE_DRY_RUN": "1",
    }
    cfg = Config.from_env(env)
    assert cfg.icu_api_key == "key"
    assert cfg.icu_athlete_id == "42"
    assert cfg.lookback_days == 14
    assert cfg.dry_run is True
    assert cfg.token_store == str(tmp_path / "garmin_tokens.json")
    assert cfg.state_path == tmp_path / "state.json"


def test_config_defaults(tmp_path):
    env = {
        "ICU_API_KEY": "key",
        "GARMIN_EMAIL": "a@b.c",
        "GARMIN_PASSWORD": "pw",
        "BRIDGE_DATA_DIR": str(tmp_path),
    }
    cfg = Config.from_env(env)
    assert cfg.icu_athlete_id == "0"
    assert cfg.lookback_days == 7
    assert cfg.dry_run is False


def test_config_missing_required():
    with pytest.raises(ValueError, match="ICU_API_KEY"):
        Config.from_env({})
