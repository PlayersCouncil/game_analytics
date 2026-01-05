"""
Pydantic models for API responses.
"""

from datetime import date
from typing import Optional
from pydantic import BaseModel


class DateRange(BaseModel):
    start: Optional[date] = None
    end: Optional[date] = None


class CardStats(BaseModel):
    blueprint: str
    name: Optional[str] = None  # Populated if card_catalog available
    games: int
    copies: int
    inclusion_wr: float
    unique_players: int = 0  # Distinct players who included this card
    played_games: int
    played_wr: Optional[float] = None
    priority: float  # games * (wr - 0.5)


class CardStatsResponse(BaseModel):
    format: str
    date_range: DateRange
    outcome_tiers: Optional[list[int]] = None
    competitive_tiers: Optional[list[int]] = None
    total_cards: int
    total_games: int = 0
    cards: list[CardStats]


class FormatCardStats(BaseModel):
    games: int
    copies: int
    inclusion_wr: float
    played_games: int
    played_wr: Optional[float] = None
    priority: float


class CompareCardStats(BaseModel):
    blueprint: str
    name: Optional[str] = None
    stats: dict[str, FormatCardStats]  # format_name -> stats


class CardCompareResponse(BaseModel):
    date_range: DateRange
    outcome_tiers: Optional[list[int]] = None
    competitive_tiers: Optional[list[int]] = None
    cards: list[CompareCardStats]


class BalancePatch(BaseModel):
    id: int
    patch_name: str
    patch_date: date
    notes: Optional[str] = None


class PatchListResponse(BaseModel):
    patches: list[BalancePatch]


class ComputationStatus(BaseModel):
    id: int
    computation_type: str
    started_at: str
    completed_at: Optional[str] = None
    records_processed: Optional[int] = None
    status: str
    error_message: Optional[str] = None


class AdminStatusResponse(BaseModel):
    recent_computations: list[ComputationStatus]
    total_games_analyzed: int
    total_card_stat_rows: int
    latest_game_date: Optional[date] = None


class CardCorrelation(BaseModel):
    blueprint: str
    together_count: int           # Times appearing together
    target_count: int             # Times target card appears
    correlated_count: int         # Times correlated card appears
    total_decks: int              # Total decks in format/side
    jaccard: float                # Intersection / Union
    lift: float                   # Key metric: how much more than chance
    side: str


class CorrelationResponse(BaseModel):
    target_blueprint: Optional[str] = None
    format_name: str
    correlations: list[CardCorrelation]
