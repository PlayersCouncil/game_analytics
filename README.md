# GEMP Game Analytics

Card analytics for Lord of the Rings TCG balance analysis. Processes JSON game summaries from GEMP replays into analytics database tables for card performance analysis.

## Quick Start (Docker)

1. **Ensure GEMP is running** (creates required network)

2. **Create database schema**:
   ```bash
   mysql -h <DB_HOST> -u gempuser -p gemp_db < schema.sql
   ```

3. **Configure and start**:
   ```bash
   cd docker
   cp .env.example .env
   # Edit .env with your settings
   docker compose up -d
   ```

4. **Access dashboard**: http://localhost:8001

See `docker/README.md` for detailed setup instructions.

## Components

- **Ingestion** (`ingest.py`) - Processes game replay summaries into database
- **Pre-computation** (`precompute.py`) - Aggregates daily stats for fast queries
- **API** (`api/`) - FastAPI service for balance team queries
- **Dashboard** (`static/index.html`) - Web UI for browsing card stats

## Configuration

All configuration is held in the environment variables stored in .env. See that file for details.

## Usage

This is for manual usage calling the python scripts directly.  When the app is hosted via docker, use the UI to access it.

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

- PC Formats
    - Fellowship Block (PC)
    - Movie Block (PC)
    - Expanded (PC)
- Main Decipher Formats
    - Fellowship Block
    - Movie Block
    - Expanded
    - Towers Standard
    - Towers Block
- Sealed Formats
    - Limited - FOTR
    - Limited - TTT
    - Limited - ROTK
    - Limited - WOTR
    - Limited - TH

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
- **priority**: `games × (inclusion_wr - 0.5)` - impact score

## Blueprint Normalization

Card IDs are normalized to canonical form:
1. Cosmetic suffixes stripped (`*` for foil, `T` for tengwar)
2. Errata sets mapped (50-69 → 0-19)
3. Promo/alt-art mapped via `blueprintMapping.txt`

## Known Limitations

- **was_played accuracy**: Until metadataVersion >= 3, attachments (weapons, armor, etc.) may not be counted as "played" due to a tracking bug. Inclusion stats are accurate for all cards.

### Re-processing

After logic changes:
1. Increment `PROCESSING_VERSION` in `ingest.py`
2. Clear old data:
   ```sql
   DELETE FROM game_analysis WHERE processing_version < 2;
   ```
3. Re-run ingestion and precompute


## File Structure

```
game_analytics/
├── ingest.py              # Game ingestion script
├── precompute.py          # Stats pre-computation
├── blueprint_normalizer.py
├── config.py
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
├── docker/
│   ├── .env.example
│   ├── analytics.Dockerfile
│   ├── crontab
│   ├── docker-compose.yml 
│   ├── entrypoint.sh
│   └── README.md
├── logs/
├── static/
│   └── index.html
├── test_normalizer.py
├── README.md
└── LICENSE
```
