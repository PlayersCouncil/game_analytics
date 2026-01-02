# GEMP Game Analytics Ingestion

Processes JSON game summaries from GEMP replays into analytics database tables for card performance analysis.

## Prerequisites

- Python 3.8+
- MySQL/MariaDB with analytics schema (see `schema.sql`)
- Access to GEMP replay directory
- `blueprintMapping.txt` from GEMP source

## Installation

```bash
pip install mysql-connector-python
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

## Usage

### Process all unprocessed games
```bash
python ingest.py
```

### Limit processing (for testing or incremental runs)
```bash
python ingest.py --limit 1000
```

### Dry run (validate without inserting)
```bash
python ingest.py --dry-run
```

### Custom batch size
```bash
python ingest.py --batch-size 200
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

## Blueprint Normalization

Card IDs are normalized to canonical form:
1. Cosmetic suffixes stripped (`*` for foil, `T` for tengwar)
2. Errata sets mapped (50-69 → 0-19)
3. Promo/alt-art mapped via `blueprintMapping.txt`

## Re-processing

To re-process games after logic changes:
1. Increment `PROCESSING_VERSION` in `ingest.py`
2. Delete from `game_analysis` where `processing_version < NEW_VERSION`
3. Run ingestion normally

```sql
DELETE FROM game_analysis WHERE processing_version < 2;
```

The CASCADE constraint will clean up `game_deck_cards` automatically.

## Logging

Logs written to `ingest.log` and stdout. Includes:
- Progress updates every 1000 games
- Warnings for skipped files (missing, malformed, wrong metadata version)
- Errors for processing failures
- Summary statistics on completion

## File Structure

```
game_analytics/
├── ingest.py              # Main ingestion script
├── blueprint_normalizer.py # Blueprint ID normalization
├── config.py              # Configuration management
├── config.ini             # Local configuration (gitignored)
├── config.ini.example     # Example configuration
├── blueprintMapping.txt   # Promo mapping (from GEMP)
├── schema.sql             # Database schema
└── README.md              # This file
```

## Cron Setup

For daily processing:

```cron
0 3 * * * cd /path/to/game_analytics && python ingest.py >> /var/log/gemp_analytics.log 2>&1
```
