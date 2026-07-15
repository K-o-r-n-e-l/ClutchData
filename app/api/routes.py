from fastapi import APIRouter
from app.schemas.player import PlayerStatsResponse
from app.services.stats import get_player_stats

router = APIRouter(prefix="/api")

@router.get("/stats/{player_id}", response_model=PlayerStatsResponse)
def read_player_stats(player_id: str):
    """Pobierz statystyki gracza CS2."""
    return get_player_stats(player_id)
