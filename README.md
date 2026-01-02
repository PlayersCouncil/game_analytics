# GEMP Game Analytics

Processes JSON game summaries from GEMP replays into analytics database tables for card performance analysis.

## Components

1. **Ingestion Script** (`ingest.py`) - Reads game summaries, populates raw data tables
2. **Pre-computation Script** (`precompute.py`) - Aggregates daily statistics for fast queries
3. **FastAPI Service** (`api/`) - REST API for balance team queries

## Prerequisites

- Python 3.8+
- MySQL/MariaDB with analytics schema (see `schema.sql`)
- Access to GEMP replay directory
- `blueprintMapping.txt` from GEMP source

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Copy `config.ini.example` to `config.ini` and edit:

```ini
[database]
host = localhost
port = 3306
user = gemp
password = your_password
name = gemp_db

[paths]
replay_base = /replay
mapping_file = blueprintMapping.txt
```

Alternatively, use environment variables:
- `GEMP_DB_HOST`, `GEMP_DB_PORT`, `GEMP_DB_USER`, `GEMP_DB_PASSWORD`, `GEMP_DB_NAME`
- `GEMP_REPLAY_PATH`, `GEMP_MAPPING_FILE`

For the API, also set:
- `GEMP_ANALYTICS_ADMIN_KEY` - API key for admin endpoints

## Usage

### Ingestion
```bash
python ingest.py                    # Process up to 500 unprocessed games
python ingest.py --limit 1000       # Process up to 1000 games
python ingest.py --dry-run          # Validate without inserting
```

### Pre-computation
```bash
python precompute.py                # Compute stats for yesterday
python precompute.py --date 2024-01-15
python precompute.py --rebuild      # Full rebuild of all stats
```

### API Server
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Development with auto-reload
uvicorn api.main:app --reload
```

API documentation available at `http://localhost:8000/docs`

## API Endpoints

### Card Statistics
```
GET /api/stats/cards
  ?format=Movie Block (PC)     # Required
  &start=2024-01-01            # Optional date range
  &end=2024-06-01
  &patch=V3_release            # Use patch date as start
  &min_games=10                # Minimum games threshold
  &sort=priority|winrate|games
  &limit=100
  &outcome_tier=1,2            # 1=Decisive, 2=Late Concession, 3=Ambiguous
  &competitive_tier=3,4        # 1=Casual, 2=League, 3=Tournament, 4=Championship
```

### Format Comparison
```
GET /api/stats/cards/compare
  ?formats=Movie Block (PC),Fellowship Block (PC)
  &start=...&end=...
  &min_games=10
```

### Balance Patches
```
GET  /api/patches              # List all patches
POST /api/patches              # Create patch (admin)
DELETE /api/patches/{id}       # Delete patch (admin)
```

### Admin
```
GET  /api/admin/status         # System status
POST /api/admin/precompute     # Trigger pre-computation (admin)
```

## Target Formats

Only games in these formats are processed:

- Fellowship Block (PC)
- Movie Block (PC)
- Expanded (PC)
- Fellowship Block
- Movie Block
- Expanded
- Towers Standard
- Towers Block
- Limited - FOTR
- Limited - TTT
- Limited - ROTK

## Classification Tiers

### Outcome Tier
- **Tier 1 (Decisive)**: Clear game-ending condition (site 9 survival, corruption, ring-bearer death)
- **Tier 2 (Late Concession)**: Concession or timeout at site 6+
- **Tier 3 (Ambiguous)**: Early quit, bot issues, unclear outcome

### Competitive Tier
- **Tier 1**: Casual games
- **Tier 2**: League games
- **Tier 3**: Tournament games
- **Tier 4**: Championship games (tournament_id contains 'wc')

## Card Metrics

- **inclusion_wr**: Win rate when card is in deck (regardless of whether played)
- **played_wr**: Win rate when card was actually played during the game
- **priority**: `games * (inclusion_wr - 0.5)` - impact score for balance analysis

## Blueprint Normalization

Card IDs are normalized to canonical form:
1. Cosmetic suffixes stripped (`*` for foil, `T` for tengwar)
2. Errata sets mapped (50-69 → 0-19)
3. Promo/alt-art mapped via `blueprintMapping.txt`

## Known Limitations

- **was_played accuracy**: Until metadataVersion >= 3, attachments (weapons, armor, etc.) may not be counted as "played" due to a tracking bug. Inclusion stats are accurate for all cards.

## Re-processing

To re-process games after logic changes:
1. Increment `PROCESSING_VERSION` in `ingest.py`
2. Delete from `game_analysis` where `processing_version < NEW_VERSION`
3. Run ingestion normally

```sql
DELETE FROM game_analysis WHERE processing_version < 2;
```

The CASCADE constraint will clean up `game_deck_cards` automatically.
Then run `python precompute.py --rebuild` to regenerate stats.

## Cron Setup

```cron
# Daily ingestion at 2 AM
0 2 * * * cd /path/to/game_analytics && python ingest.py >> /var/log/gemp_ingest.log 2>&1

# Daily pre-computation at 3 AM
0 3 * * * cd /path/to/game_analytics && python precompute.py >> /var/log/gemp_precompute.log 2>&1
```

## File Structure

```
game_analytics/
├── ingest.py              # Game ingestion script
├── precompute.py          # Stats pre-computation
├── blueprint_normalizer.py
├── config.py
├── config.ini
├── config.ini.example
├── blueprintMapping.txt
├── schema.sql
├── requirements.txt
├── api/
│   ├── __init__.py
│   ├── main.py            # FastAPI app
│   ├── models/
│   │   ├── __init__.py
│   │   ├── requests.py
│   │   └── responses.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── cards.py
│   │   ├── patches.py
│   │   └── admin.py
│   └── services/
│       ├── __init__.py
│       ├── card_stats.py
│       └── patch_service.py
├── test_normalizer.py
└── README.md
```
