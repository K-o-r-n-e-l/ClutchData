from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from app.db.models import Player, EloHistory, Match, MatchStatistic, MatchRound, PlayerRoundStatistic
from datetime import datetime
from typing import Optional, Dict, Any

def parse_faceit_datetime(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val)
        except Exception:
            return None
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return None
    return None

async def save_faceit_elo(db: AsyncSession, steam_id: str, persona_name: str, faceit_elo: int):
    # 1. Szukamy gracza w naszej bazie
    result = await db.execute(select(Player).filter(Player.steam_id == steam_id))
    player = result.scalars().first()

    # 2. Jeśli go nie ma, tworzymy nowy wpis gracza
    if not player:
        player = Player(steam_id=steam_id, persona_name=persona_name)
        db.add(player)
        await db.commit()
        await db.refresh(player)
    else:
        # Jeśli istnieje, ale zmienił nick - aktualizujemy go
        if player.persona_name != persona_name and persona_name:
            player.persona_name = persona_name
            await db.commit()

    # 3. Sprawdzamy jego ostatnio zapisane ELO
    stmt = select(EloHistory).filter(EloHistory.player_id == player.id).order_by(EloHistory.id.desc())
    result = await db.execute(stmt)
    last_record = result.scalars().first()

    # 4. Jeśli nie ma żadnego zapisu, albo jego ELO się zmieniło od ostatniego razu - zapisujemy nowy punkt na wykresie!
    if not last_record or last_record.faceit_elo != faceit_elo:
        new_record = EloHistory(player_id=player.id, faceit_elo=faceit_elo)
        db.add(new_record)
        await db.commit()

async def get_player_by_steam_id(db: AsyncSession, steam_id: str) -> Optional[Player]:
    result = await db.execute(select(Player).filter(Player.steam_id == steam_id))
    return result.scalars().first()

async def enable_clutchdata_plus(db: AsyncSession, steam_id: str) -> bool:
    player = await get_player_by_steam_id(db, steam_id)
    if player:
        player.clutchdata_plus = True
        await db.commit()
        return True
    return False

async def get_match_by_faceit_id(db: AsyncSession, faceit_match_id: str) -> Optional[Match]:
    result = await db.execute(select(Match).filter(Match.faceit_match_id == faceit_match_id))
    return result.scalars().first()

async def is_match_analyzed(db: AsyncSession, faceit_match_id: str) -> bool:
    match = await get_match_by_faceit_id(db, faceit_match_id)
    return bool(match and match.is_analyzed)

async def save_analyzed_demo_data(
    db: AsyncSession,
    faceit_match_id: str,
    match_info: Dict[str, Any],
    parsed_data: Dict[str, Any]
) -> Match:
    """
    Zapisuje przetworzone statystyki dema (Match, MatchRound, PlayerRoundStatistic, MatchStatistic) do bazy danych.
    """
    # 1. Sprawdź lub utwórz mecz
    result = await db.execute(select(Match).filter(Match.faceit_match_id == faceit_match_id))
    match = result.scalars().first()

    # Określ mapę i czasy
    map_pick = match_info.get("voting", {}).get("map", {}).get("pick")
    map_name = map_pick[0] if isinstance(map_pick, list) and map_pick else match_info.get("game_data", {}).get("map", "Unknown")
    started_at = parse_faceit_datetime(match_info.get("started_at"))
    finished_at = parse_faceit_datetime(match_info.get("finished_at"))

    if not match:
        match = Match(
            faceit_match_id=faceit_match_id,
            map_name=map_name,
            started_at=started_at,
            finished_at=finished_at,
            is_analyzed=True
        )
        db.add(match)
        await db.flush()
        await db.refresh(match)
    else:
        match.is_analyzed = True
        if map_name:
            match.map_name = map_name
        if started_at:
            match.started_at = started_at
        if finished_at:
            match.finished_at = finished_at

        # Usuń poprzednie statystyki i rundy w razie ponownej analizy
        r_ids_res = await db.execute(select(MatchRound.id).where(MatchRound.match_id == match.id))
        r_ids = r_ids_res.scalars().all()
        if r_ids:
            await db.execute(delete(PlayerRoundStatistic).where(PlayerRoundStatistic.match_round_id.in_(r_ids)))
        await db.execute(delete(MatchStatistic).where(MatchStatistic.match_id == match.id))
        await db.execute(delete(MatchRound).where(MatchRound.match_id == match.id))
        await db.flush()

    df_rounds = parsed_data['match_rounds']
    df_player_round_stats = parsed_data['player_round_statistics']
    df_match_stats = parsed_data['match_statistics']

    # 2. Utwórz lub znajdź graczy na podstawie steam_id
    player_id_map = {}
    for _, row in df_match_stats.iterrows():
        sid = str(row.get('steam_id', ''))
        pname = str(row.get('player_name', sid))
        if not sid or sid == '0':
            continue

        p_res = await db.execute(select(Player).filter(Player.steam_id == sid))
        player = p_res.scalars().first()
        if not player:
            player = Player(steam_id=sid, persona_name=pname)
            db.add(player)
            await db.flush()
            await db.refresh(player)
        else:
            if pname and (not player.persona_name or player.persona_name == sid):
                player.persona_name = pname

        player_id_map[sid] = player.id

    # 3. Zapisz rundy meczu
    round_id_map = {}
    for _, r_row in df_rounds.iterrows():
        r_num = int(r_row['round_number'])
        mr = MatchRound(
            match_id=match.id,
            round_number=r_num,
            winning_side=str(r_row.get('winning_side', '')),
            win_reason=str(r_row.get('win_reason', '')),
            duration_seconds=float(r_row.get('duration_seconds', 0.0))
        )
        db.add(mr)
        await db.flush()
        await db.refresh(mr)
        round_id_map[r_num] = mr.id

    # 4. Zapisz statystyki rundowe graczy
    for _, pr_row in df_player_round_stats.iterrows():
        sid = str(pr_row.get('steam_id', ''))
        r_num = int(pr_row.get('round_number', 1))
        pid = player_id_map.get(sid)
        m_round_id = round_id_map.get(r_num)
        if not pid or not m_round_id:
            continue

        prs = PlayerRoundStatistic(
            match_round_id=m_round_id,
            player_id=pid,
            side_played=str(pr_row.get('side_played', 'CT')),
            clutchdata_rating_impact=float(pr_row.get('clutchdata_rating_impact', 0.0)),
            kills=int(pr_row.get('kills', 0)),
            assists=int(pr_row.get('assists', 0)),
            deaths=int(pr_row.get('deaths', 0)),
            damage_dealt=float(pr_row.get('damage_dealt', 0.0)),
            utility_damage=float(pr_row.get('utility_damage', 0.0)),
            enemies_flashed=int(pr_row.get('enemies_flashed', 0)),
            trade_kills=int(pr_row.get('trade_kills', 0)),
            was_entry_attempt=bool(pr_row.get('was_entry_attempt', False)),
            was_entry_success=bool(pr_row.get('was_entry_success', False)),
            clutch_scenario=str(pr_row.get('clutch_scenario')) if pr_row.get('clutch_scenario') and str(pr_row.get('clutch_scenario')) != 'None' else None,
            clutch_won=bool(pr_row.get('clutch_won', False))
        )
        db.add(prs)

    # 5. Zapisz podsumowanie statystyk meczu
    for _, ms_row in df_match_stats.iterrows():
        sid = str(ms_row.get('steam_id', ''))
        pid = player_id_map.get(sid)
        if not pid:
            continue

        cr = float(ms_row.get('clutchdata_rating', 0.0))
        ms = MatchStatistic(
            match_id=match.id,
            player_id=pid,
            clutchdata_rating=cr,
            ClutchRating=cr,
            entry_attempts=int(ms_row.get('entry_attempts', 0)),
            entry_success=int(ms_row.get('entry_success', 0)),
            clutch_1v1_attempts=int(ms_row.get('clutch_1v1_attempts', 0)),
            clutch_1v2_attempts=int(ms_row.get('clutch_1v2_attempts', 0)),
            clutch_1v3_attempts=int(ms_row.get('clutch_1v3_attempts', 0)),
            clutch_1v4_attempts=int(ms_row.get('clutch_1v4_attempts', 0)),
            clutch_1v5_attempts=int(ms_row.get('clutch_1v5_attempts', 0)),
            clutch_1v1_wins=int(ms_row.get('clutch_1v1_wins', 0)),
            clutch_1v2_wins=int(ms_row.get('clutch_1v2_wins', 0)),
            clutch_1v3_wins=int(ms_row.get('clutch_1v3_wins', 0)),
            clutch_1v4_wins=int(ms_row.get('clutch_1v4_wins', 0)),
            clutch_1v5_wins=int(ms_row.get('clutch_1v5_wins', 0)),
            trade_kills=int(ms_row.get('trade_kills', 0)),
            utility_damage=int(ms_row.get('utility_damage', 0)),
            enemies_flashed=int(ms_row.get('enemies_flashed', 0)),
            flash_assists=int(ms_row.get('flash_assists', 0)),
            kills=int(ms_row.get('kills', 0)),
            deaths=int(ms_row.get('deaths', 0)),
            assists=int(ms_row.get('assists', 0)),
            adr=float(ms_row.get('adr', 0.0)),
            total_damage=float(ms_row.get('total_damage', 0.0))
        )
        db.add(ms)

    await db.commit()
    return match

async def get_full_analyzed_match_data(db: AsyncSession, faceit_match_id: str) -> Optional[Dict[str, Any]]:
    """
    Pobiera pełne dane przeanalizowanego meczu z bazy danych w formacie przygotowanym do szablonu HTML.
    """
    result = await db.execute(select(Match).filter(Match.faceit_match_id == faceit_match_id))
    match = result.scalars().first()
    if not match or not match.is_analyzed:
        return None

    # Statystyki meczowe graczy
    stmt_stats = (
        select(MatchStatistic, Player)
        .join(Player, MatchStatistic.player_id == Player.id)
        .filter(MatchStatistic.match_id == match.id)
        .order_by(MatchStatistic.clutchdata_rating.desc())
    )
    stats_res = await db.execute(stmt_stats)
    stats_rows = stats_res.all()

    player_stats_list = []
    for ms, p in stats_rows:
        total_clutches_att = (ms.clutch_1v1_attempts + ms.clutch_1v2_attempts + ms.clutch_1v3_attempts + ms.clutch_1v4_attempts + ms.clutch_1v5_attempts)
        total_clutches_won = (ms.clutch_1v1_wins + ms.clutch_1v2_wins + ms.clutch_1v3_wins + ms.clutch_1v4_wins + ms.clutch_1v5_wins)
        
        entry_pct = round((ms.entry_success / ms.entry_attempts * 100), 1) if ms.entry_attempts > 0 else 0.0
        kd = round(ms.kills / ms.deaths, 2) if ms.deaths > 0 else float(ms.kills)

        player_stats_list.append({
            "player_id": p.id,
            "steam_id": p.steam_id,
            "persona_name": p.persona_name or p.steam_id,
            "clutchdata_rating": ms.clutchdata_rating,
            "kills": ms.kills,
            "deaths": ms.deaths,
            "assists": ms.assists,
            "kd": kd,
            "adr": ms.adr,
            "total_damage": ms.total_damage,
            "entry_attempts": ms.entry_attempts,
            "entry_success": ms.entry_success,
            "entry_rate": entry_pct,
            "trade_kills": ms.trade_kills,
            "utility_damage": ms.utility_damage,
            "enemies_flashed": ms.enemies_flashed,
            "flash_assists": ms.flash_assists,
            "clutches_won": total_clutches_won,
            "clutches_total": total_clutches_att,
            "c_1v1": f"{ms.clutch_1v1_wins}/{ms.clutch_1v1_attempts}",
            "c_1v2": f"{ms.clutch_1v2_wins}/{ms.clutch_1v2_attempts}",
            "c_1v3": f"{ms.clutch_1v3_wins}/{ms.clutch_1v3_attempts}",
            "c_1v4": f"{ms.clutch_1v4_wins}/{ms.clutch_1v4_attempts}",
            "c_1v5": f"{ms.clutch_1v5_wins}/{ms.clutch_1v5_attempts}",
            "c_1v1_wins": ms.clutch_1v1_wins,
            "c_1v1_attempts": ms.clutch_1v1_attempts,
            "c_1v2_wins": ms.clutch_1v2_wins,
            "c_1v2_attempts": ms.clutch_1v2_attempts,
            "c_1v3_wins": ms.clutch_1v3_wins,
            "c_1v3_attempts": ms.clutch_1v3_attempts,
            "c_1v4_wins": ms.clutch_1v4_wins,
            "c_1v4_attempts": ms.clutch_1v4_attempts,
            "c_1v5_wins": ms.clutch_1v5_wins,
            "c_1v5_attempts": ms.clutch_1v5_attempts,
        })

    # Rundy meczu
    stmt_rounds = (
        select(MatchRound)
        .filter(MatchRound.match_id == match.id)
        .order_by(MatchRound.round_number.asc())
    )
    rounds_res = await db.execute(stmt_rounds)
    rounds_list = rounds_res.scalars().all()

    rounds_data = []
    for r in rounds_list:
        stmt_prs = (
            select(PlayerRoundStatistic, Player)
            .join(Player, PlayerRoundStatistic.player_id == Player.id)
            .filter(PlayerRoundStatistic.match_round_id == r.id)
            .order_by(PlayerRoundStatistic.clutchdata_rating_impact.desc())
        )
        prs_res = await db.execute(stmt_prs)
        prs_rows = prs_res.all()

        round_player_stats = []
        mvp_name = None
        highest_impact = -999.0

        for prs, p in prs_rows:
            if prs.clutchdata_rating_impact > highest_impact:
                highest_impact = prs.clutchdata_rating_impact
                mvp_name = p.persona_name or p.steam_id

            round_player_stats.append({
                "steam_id": p.steam_id,
                "persona_name": p.persona_name or p.steam_id,
                "side_played": prs.side_played,
                "impact": prs.clutchdata_rating_impact,
                "kills": prs.kills,
                "assists": prs.assists,
                "deaths": prs.deaths,
                "damage_dealt": prs.damage_dealt,
                "utility_damage": prs.utility_damage,
                "enemies_flashed": prs.enemies_flashed,
                "trade_kills": prs.trade_kills,
                "entry_success": prs.was_entry_success,
                "entry_attempt": prs.was_entry_attempt,
                "clutch_scenario": prs.clutch_scenario,
                "clutch_won": prs.clutch_won
            })

        rounds_data.append({
            "round_number": r.round_number,
            "winning_side": r.winning_side,
            "win_reason": r.win_reason,
            "duration_seconds": r.duration_seconds,
            "mvp": mvp_name,
            "players": round_player_stats
        })

    return {
        "match": {
            "id": match.id,
            "faceit_match_id": match.faceit_match_id,
            "map_name": match.map_name,
            "started_at": match.started_at.isoformat() if match.started_at else None,
            "finished_at": match.finished_at.isoformat() if match.finished_at else None,
            "is_analyzed": match.is_analyzed
        },
        "player_stats": player_stats_list,
        "rounds": rounds_data,
        "total_rounds": len(rounds_data)
    }
