from typing import Optional


class Player:
    def __init__(self, player_id: str, nickname: str, team: Optional[str] = None):
        self.player_id = player_id
        self.nickname = nickname
        self.team = team
