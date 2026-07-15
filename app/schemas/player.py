from pydantic import BaseModel


class PlayerStatsResponse(BaseModel):
    player_id: str
    nickname: str
    matches_played: int
    kills: int
    deaths: int
    clutch_wins: int
    rating: float

    class Config:
        from_attributes = True
