# mywhoosh-garmin-bridge

Syncs indoor trainer rides (MyWhoosh) from [intervals.icu](https://intervals.icu) to
[Garmin Connect](https://connect.garmin.com), rewriting the FIT file so it looks like it
was recorded on a **Garmin Edge 840**. This unlocks Garmin's server-side Firstbeat metrics
for those rides: **Training Status, Training Load, Training Effect**, power-based metrics
(IF, NP), and full power/HR/cadence time series in the activity view.

## How it works

1. Lists your recent activities on intervals.icu (personal API key, basic auth).
2. For each **Ride**, downloads the original FIT file (falls back to intervals.icu's
   regenerated FIT if the original can't be fetched).
3. Checks the FIT: if it has **power data** and the `file_id` manufacturer is **not Garmin**,
   it's an indoor ride (MyWhoosh/Zwift uploads identify themselves as the app, not a bike
   computer). Rides already recorded on a Garmin device are left alone.
4. Rewrites the FIT in place (`mywhoosh_garmin_bridge/fit.py`):
   - `file_id`: `manufacturer=garmin`, `product=edge_840` (4062), `type=activity`,
     serial + `time_created` from the ride start
   - `device_info`: Garmin / Edge 840 / bike-computer device type / LOCAL source
   - `session`/`lap`/`activity`: `sport=cycling`, recomputed avg/max power (incl.
     Normalized Power), HR, cadence, distance, ascent, timer
   - keeps the original 1 Hz record stream (HR, power, cadence, speed, altitude)
   - CRC is recomputed and the result is validated before upload
5. Checks Garmin Connect for an existing cycling activity starting within ±5 minutes of the
   ride (dedupe window). If found, the ride is marked processed and skipped.
6. Uploads the rewritten FIT to Garmin Connect's upload service.
7. Records the activity id in a local state file so re-runs never double-upload.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
# fill in .env: ICU_API_KEY, GARMIN_EMAIL, GARMIN_PASSWORD
```

- **ICU_API_KEY**: intervals.icu → Settings → Developer Settings → API key
- **ICU_ATHLETE_ID**: `0` = the athlete the API key belongs to (default)
- **GARMIN_EMAIL / GARMIN_PASSWORD**: your Garmin Connect login. On first run the OAuth
  tokens are cached in `.data/garmin_tokens.json`; later runs reuse them and only re-login
  when the token expires. If your account has MFA, run once interactively.

## Running

Dry run first (no Garmin login, no uploads — state is still updated so a follow-up real run
won't reprocess, so delete `.data/state.json` if you want a clean re-test):

```bash
.venv/bin/python -m mywhoosh_garmin_bridge --dry-run -v
```

Real run:

```bash
.venv/bin/python -m mywhoosh_garmin_bridge
```

### Cron (every 30 minutes)

```cron
*/30 * * * * cd /path/to/mywhoosh-garmin-bridge && /path/to/mywhoosh-garmin-bridge/.venv/bin/python -m mywhoosh_garmin_bridge >> /var/log/mywhoosh-garmin-bridge.log 2>&1
```

## Configuration

| Env var                | Default  | Meaning                                             |
| ---------------------- | -------- | --------------------------------------------------- |
| `ICU_API_KEY`          | required | intervals.icu personal API key                      |
| `ICU_ATHLETE_ID`       | `0`      | athlete id (`0` = key owner)                        |
| `GARMIN_EMAIL`         | required | Garmin Connect email                                |
| `GARMIN_PASSWORD`      | required | Garmin Connect password                             |
| `BRIDGE_DATA_DIR`      | `.data`  | state + Garmin token store location                 |
| `BRIDGE_LOOKBACK_DAYS` | `7`      | how many days back to scan each run                 |
| `BRIDGE_DRY_RUN`       | `0`      | `1` = process but never upload                      |

## Tests

```bash
.venv/bin/python -m pytest
```

## Caveats

- Uploading device-spoofed FIT files uses Garmin's undocumented upload API; Garmin can
  change or restrict it at any time.
- Rides without heart-rate data are skipped: Garmin cannot compute Training Effect /
  Training Load from power alone.
- If intervals.icu holds the activity only as a Strava-sourced record, the original file
  may be unavailable; the bridge falls back to intervals.icu's regenerated FIT.
- `file_id.time_created` is set from the ride start, and the uploaded activity keeps the
  original name only implicitly (Garmin derives it from the file); rename in Garmin Connect
  if you want the MyWhoosh route name.
