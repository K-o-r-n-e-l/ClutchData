def calculate_clutch_rate(wins: int, rounds: int) -> float:
    if rounds == 0:
        return 0.0
    return round(wins / rounds * 100, 2)
