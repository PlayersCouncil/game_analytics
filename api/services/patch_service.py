"""
Balance patch management service.
"""

from datetime import date
from typing import Optional

from ..models import BalancePatch


def get_all_patches(cursor) -> list[BalancePatch]:
    """Get all balance patches, ordered by date descending."""
    cursor.execute("""
        SELECT id, patch_name, patch_date, notes
        FROM balance_patches
        ORDER BY patch_date DESC
    """)
    
    return [
        BalancePatch(
            id=row[0],
            patch_name=row[1],
            patch_date=row[2],
            notes=row[3]
        )
        for row in cursor.fetchall()
    ]


def get_patch_by_name(cursor, patch_name: str) -> Optional[BalancePatch]:
    """Get a specific patch by name."""
    cursor.execute("""
        SELECT id, patch_name, patch_date, notes
        FROM balance_patches
        WHERE patch_name = %s
    """, (patch_name,))
    
    row = cursor.fetchone()
    if row:
        return BalancePatch(
            id=row[0],
            patch_name=row[1],
            patch_date=row[2],
            notes=row[3]
        )
    return None


def create_patch(cursor, patch_name: str, patch_date: date, notes: Optional[str] = None) -> int:
    """Create a new balance patch. Returns the new patch ID."""
    cursor.execute("""
        INSERT INTO balance_patches (patch_name, patch_date, notes)
        VALUES (%s, %s, %s)
    """, (patch_name, patch_date, notes))
    
    return cursor.lastrowid


def delete_patch(cursor, patch_id: int) -> bool:
    """Delete a balance patch. Returns True if deleted, False if not found."""
    cursor.execute("""
        DELETE FROM balance_patches WHERE id = %s
    """, (patch_id,))
    
    return cursor.rowcount > 0
