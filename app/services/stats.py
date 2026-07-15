from app.schemas.player import PlayerStatsResponse


def get_player_stats(player_id: str) -> PlayerStatsResponse:
    """Zwraca przykładowe statystyki gracza."""
    # Później zastąp to logiką pobierającą prawdziwe dane CS2.
    return PlayerStatsResponse(
        player_id=player_id,
        nickname="ExamplePlayer",
        matches_played=42,
        kills=520,
        deaths=430,
        clutch_wins=12,
        rating=1.26,
    )
