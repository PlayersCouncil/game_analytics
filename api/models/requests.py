"""
Pydantic models for API requests.
"""

from datetime import date
from typing import Optional, Literal
from pydantic import BaseModel, Field


class CreatePatchRequest(BaseModel):
    patch_name: str = Field(..., min_length=1, max_length=100)
    patch_date: date
    notes: Optional[str] = None


class PrecomputeRequest(BaseModel):
    mode: Literal['incremental', 'full_rebuild', 'date_range']
    date: Optional[date] = None  # For incremental mode, specific date to compute
    start_date: Optional[date] = None  # For date_range mode
    end_date: Optional[date] = None  # For date_range mode
