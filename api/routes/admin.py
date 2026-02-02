"""
Admin endpoints for analytics management.
"""

import subprocess
import sys
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Header, BackgroundTasks

from ..models import PrecomputeRequest, AdminStatusResponse, ComputationStatus
from ..main import get_db_cursor

router = APIRouter(prefix="/admin", tags=["admin"])


def verify_admin_key(x_api_key: Optional[str] = Header(None)):
    """Simple API key verification for admin endpoints."""
    import os
    expected_key = os.environ.get('GEMP_ANALYTICS_ADMIN_KEY')
    if not expected_key:
        raise HTTPException(500, "Admin key not configured")
    if x_api_key != expected_key:
        raise HTTPException(403, "Invalid or missing API key")


def run_precompute(mode: str, target_date: Optional[date] = None, start_date: Optional[date] = None, end_date: Optional[date] = None):
    """Run precompute.py in subprocess."""
    cmd = [sys.executable, 'precompute.py']
    
    if mode == 'full_rebuild':
        cmd.append('--rebuild')
    elif mode == 'date_range' and start_date and end_date:
        cmd.extend(['--start-date', start_date.isoformat(), '--end-date', end_date.isoformat()])
    elif target_date:
        cmd.extend(['--date', target_date.isoformat()])
    
    subprocess.run(cmd, check=True)


def run_catalog_rebuild():
    """Run build_catalog.py in subprocess."""
    cmd = [sys.executable, 'build_catalog.py']
    subprocess.run(cmd, check=True)


def run_detect_archetypes(
    format_name: Optional[str] = None, 
    patch_name: Optional[str] = None,
    resolution: float = 7.5
):
    """Run detect_archetypes.py in subprocess."""
    cmd = [sys.executable, 'detect_archetypes.py', '--resolution', str(resolution)]
    if format_name:
        cmd.extend(['--format', format_name])
    if patch_name:
        cmd.extend(['--patch', patch_name])
    subprocess.run(cmd, check=True)


def run_ingest(limit: int = 1000):
    """Run ingest.py in subprocess."""
    cmd = [sys.executable, 'ingest.py', '--limit', str(limit)]
    subprocess.run(cmd, check=True)


@router.post("/ingest", dependencies=[Depends(verify_admin_key)])
def trigger_ingest(
    background_tasks: BackgroundTasks,
    limit: int = 1000,
):
    """
    Trigger ingestion of new games from replay summaries.
    
    - **limit**: Maximum number of games to process (default 1000)
    """
    background_tasks.add_task(run_ingest, limit)
    
    return {
        "status": "started",
        "message": f"Ingestion started (limit: {limit} games)"
    }


@router.post("/catalog/rebuild", dependencies=[Depends(verify_admin_key)])
def trigger_catalog_rebuild(background_tasks: BackgroundTasks):
    """
    Trigger rebuild of the card catalog from HJSON files.
    
    Parses all HJSON card definitions and PC_Cards.js to update
    the card_catalog table with names, cultures, and image URLs.
    """
    background_tasks.add_task(run_catalog_rebuild)
    
    return {
        "status": "started",
        "message": "Card catalog rebuild initiated"
    }


@router.post("/precompute", dependencies=[Depends(verify_admin_key)])
def trigger_precompute(
    request: PrecomputeRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger pre-computation of daily stats.
    
    - **mode**: 'incremental' for single day, 'date_range' for range, 'full_rebuild' for all data
    - **date**: For incremental mode, specific date to compute (defaults to yesterday)
    - **start_date**, **end_date**: For date_range mode
    """
    target_date = request.date
    start_date = request.start_date
    end_date = request.end_date
    
    if request.mode == 'incremental' and not target_date:
        target_date = date.today() - timedelta(days=1)
    
    if request.mode == 'date_range':
        if not start_date or not end_date:
            raise HTTPException(400, "date_range mode requires start_date and end_date")
        if start_date > end_date:
            raise HTTPException(400, "start_date must be before or equal to end_date")
    
    # Run in background to avoid timeout
    background_tasks.add_task(run_precompute, request.mode, target_date, start_date, end_date)
    
    response = {
        "status": "started",
        "mode": request.mode,
    }
    
    if request.mode == 'date_range':
        response["start_date"] = start_date.isoformat()
        response["end_date"] = end_date.isoformat()
    elif target_date:
        response["date"] = target_date.isoformat()
    
    return response


@router.get("/status", response_model=AdminStatusResponse)
def get_status(cursor = Depends(get_db_cursor)):
    """Get analytics system status."""
    
    # Recent computations
    cursor.execute("""
        SELECT id, computation_type, started_at, completed_at, 
               records_processed, status, error_message
        FROM stats_computation_log
        ORDER BY started_at DESC
        LIMIT 10
    """)
    
    computations = [
        ComputationStatus(
            id=row[0],
            computation_type=row[1],
            started_at=row[2].isoformat() if row[2] else None,
            completed_at=row[3].isoformat() if row[3] else None,
            records_processed=row[4],
            status=row[5],
            error_message=row[6],
        )
        for row in cursor.fetchall()
    ]
    
    # Total games
    cursor.execute("SELECT COUNT(*) FROM game_analysis")
    total_games = cursor.fetchone()[0]
    
    # Total stat rows
    cursor.execute("SELECT COUNT(*) FROM card_stats_daily")
    total_stat_rows = cursor.fetchone()[0]
    
    # Latest game date
    cursor.execute("SELECT MAX(game_date) FROM game_analysis")
    latest_date = cursor.fetchone()[0]
    
    return AdminStatusResponse(
        recent_computations=computations,
        total_games_analyzed=total_games,
        total_card_stat_rows=total_stat_rows,
        latest_game_date=latest_date,
    )


@router.post("/detect-archetypes", dependencies=[Depends(verify_admin_key)])
def trigger_detect_archetypes(
    background_tasks: BackgroundTasks,
    format_name: Optional[str] = None,
    patch_name: Optional[str] = None,
    resolution: float = 7.5,
):
    """
    Trigger archetype detection using Louvain community detection.
    
    - **format_name**: Optional format to process (default: all formats)
    - **patch_name**: Optional patch to process (default: all patches)
    - **resolution**: Louvain resolution parameter (default: 7.5, higher = more granular)
    
    WARNING: This will delete existing archetypes for the specified scope and rebuild from scratch.
    """
    background_tasks.add_task(run_detect_archetypes, format_name, patch_name, resolution)
    
    scope_parts = []
    if format_name:
        scope_parts.append(f"format: {format_name}")
    if patch_name:
        scope_parts.append(f"patch: {patch_name}")
    scope = ", ".join(scope_parts) if scope_parts else "all formats and patches"
    
    return {
        "status": "started",
        "message": f"Archetype detection started (resolution: {resolution}) for {scope}"
    }
