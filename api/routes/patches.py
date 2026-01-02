"""
Balance patch management endpoints.
"""

from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional

from ..models import PatchListResponse, BalancePatch, CreatePatchRequest
from ..services import get_all_patches, create_patch, delete_patch
from ..main import get_db_cursor, get_db_connection

router = APIRouter(prefix="/patches", tags=["patches"])


def verify_admin_key(x_api_key: Optional[str] = Header(None)):
    """Simple API key verification for admin endpoints."""
    import os
    expected_key = os.environ.get('GEMP_ANALYTICS_ADMIN_KEY')
    if not expected_key:
        raise HTTPException(500, "Admin key not configured")
    if x_api_key != expected_key:
        raise HTTPException(403, "Invalid or missing API key")


@router.get("", response_model=PatchListResponse)
def list_patches(cursor = Depends(get_db_cursor)):
    """List all balance patches."""
    patches = get_all_patches(cursor)
    return PatchListResponse(patches=patches)


@router.post("", response_model=BalancePatch, dependencies=[Depends(verify_admin_key)])
def add_patch(
    request: CreatePatchRequest,
    cursor = Depends(get_db_cursor),
    conn = Depends(get_db_connection),
):
    """Create a new balance patch marker. Requires admin API key."""
    try:
        patch_id = create_patch(cursor, request.patch_name, request.patch_date, request.notes)
        conn.commit()
        
        return BalancePatch(
            id=patch_id,
            patch_name=request.patch_name,
            patch_date=request.patch_date,
            notes=request.notes,
        )
    except Exception as e:
        conn.rollback()
        if "Duplicate entry" in str(e):
            raise HTTPException(409, f"Patch '{request.patch_name}' already exists")
        raise HTTPException(500, str(e))


@router.delete("/{patch_id}", dependencies=[Depends(verify_admin_key)])
def remove_patch(
    patch_id: int,
    cursor = Depends(get_db_cursor),
    conn = Depends(get_db_connection),
):
    """Delete a balance patch marker. Requires admin API key."""
    deleted = delete_patch(cursor, patch_id)
    conn.commit()
    
    if not deleted:
        raise HTTPException(404, f"Patch {patch_id} not found")
    
    return {"status": "deleted", "id": patch_id}
