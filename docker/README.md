# GEMP Analytics Docker Setup

## Prerequisites

- Docker and Docker Compose
- GEMP containers running (creates the `gemp_1_gemp_net_1` network)
- Analytics schema created in database (run `schema.sql` manually)

## Directory Structure

```
/gemp/
├── gemp-prod/
│   ├── gemp-lotr/docker/     # GEMP docker files
│   └── replay/               # Game replay files
└── game_analytics/           # This project
    ├── docker/
    │   ├── docker-compose.yml
    │   ├── .env              # Create from .env.example
    │   └── analytics.Dockerfile
    ├── api/
    ├── static/
    ├── logs/                 # Container logs
    └── ...
```

## Setup

1. **Create schema** (one-time, run from any MySQL client):
   ```bash
   mysql -h 172.28.1.3 -u gempuser -p gemp_db < schema.sql
   ```

2. **Configure environment**:
   ```bash
   cd docker
   cp .env.example .env
   # Edit .env with your settings
   ```

3. **Verify GEMP is running** (network must exist):
   ```bash
   docker network ls | grep gemp_1_gemp_net_1
   ```

4. **Start analytics**:
   ```bash
   docker compose up -d
   ```

5. **Check health**:
   ```bash
   curl http://localhost:8001/health
   ```

6. **Access dashboard**:
   Open http://localhost:8001 in browser

## Logs

Container logs are mounted to `../logs/`:
- `ingest.log` - Daily ingestion job
- `precompute.log` - Daily stats aggregation

View live logs:
```bash
docker compose logs -f analytics
```

## Cron Schedule

Jobs run during low-traffic window (0500-0800 UTC):
- **0500 UTC**: Ingestion (process new games)
- **0530 UTC**: Precompute (aggregate stats)

Jobs use `nice -n 15` and `ionice -c 2 -n 7` to minimize impact on game server.

## Manual Operations

**Run ingestion manually**:
```bash
docker compose exec analytics python ingest.py --limit 1000
```

**Full rebuild of stats**:
```bash
docker compose exec analytics python precompute.py --rebuild
```

**Check status**:
```bash
curl http://localhost:8001/api/admin/status
```

## Resource Limits

The container is limited to:
- 1.0 CPU
- 512MB memory

This ensures the game server always has priority.

## Troubleshooting

**Database connection failed**:
- Verify GEMP DB container is running
- Check IP address in .env matches `docker network inspect gemp_1_gemp_net_1`

**Network not found**:
- Start GEMP first: `cd /gemp/gemp-prod/gemp-lotr/docker && docker compose up -d`

**Replay files not found**:
- Check REPLAY_PATH in .env points to correct location
- Verify bind mount is read-only (won't create empty dir)
