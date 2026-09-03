import os
import gzip
import shutil
import asyncio
import httpx
import zstandard as zstd
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from Demo_parser import parse_demo_to_dataframes
from app.db.crud import save_analyzed_demo_data, get_full_analyzed_match_data, is_match_analyzed

TEMP_DEMOS_DIR = Path(__file__).resolve().parents[2] / "temp_demos"




def format_win_reason(reason: str, winning_side: str) -> tuple[str, str]:
    r = (reason or "").lower().replace("-", "_").replace(" ", "_")
    if "bomb_defused" in r or "defuse" in r or r == "7":
        return "🧯", "Rozbrojenie bomby"
    elif "target_bombed" in r or "bomb" in r or r == "1" or "explode" in r:
        return "💥", "Wybuch bomby"
    elif "elimination" in r or "win" in r or r in ("8", "9"):
        if winning_side == "CT":
            return "💀", "Wyeliminowanie terrorystów"
        else:
            return "💀", "Wyeliminowanie antyterrorystów"
    elif "time" in r or "saved" in r or r == "12":
        return "⏱️", "Upłynięcie czasu rundy"
    else:
        return "🏆", reason if reason else f"Wygrana {winning_side}"


def enrich_analyzed_teams(
    analysis_data: Optional[Dict[str, Any]], 
    match_info: Optional[Dict[str, Any]] = None, 
    match_stats: Optional[Dict[str, Any]] = None, 
    avatars: Optional[Dict[str, str]] = None
) -> Optional[Dict[str, Any]]:
    """
    Dzieli statystyki graczy (player_stats) na dwie drużyny (factions) na podstawie match_info / match_stats,
    przypisuje awatary i sortuje graczy w każdej drużynie malejąco wg ClutchRating.
    """
    if not analysis_data or "player_stats" not in analysis_data:
        return analysis_data

    team1_name = "Drużyna 1"
    team2_name = "Drużyna 2"
    team1_score = ""
    team2_score = ""

    # Nazwy drużyn i wyniki z match_stats
    if match_stats:
        rounds_list = match_stats.get("rounds", [])
        if rounds_list:
            teams_stats_list = rounds_list[0].get("teams", [])
            if len(teams_stats_list) > 0:
                team1_name = teams_stats_list[0].get("team_stats", {}).get("Team", team1_name)
                team1_score = teams_stats_list[0].get("team_stats", {}).get("Final Score", "")
            if len(teams_stats_list) > 1:
                team2_name = teams_stats_list[1].get("team_stats", {}).get("Team", team2_name)
                team2_score = teams_stats_list[1].get("team_stats", {}).get("Final Score", "")

    faction1_sids = set()
    faction2_sids = set()
    faction1_nicks = set()
    faction2_nicks = set()
    steam_to_avatar = {}

    team1_captain_avatar = ""
    team1_captain_name = ""
    team1_captain_id = ""

    team2_captain_avatar = ""
    team2_captain_name = ""
    team2_captain_id = ""

    teams_info = match_info.get("teams", {}) if match_info else {}
    if "faction1" in teams_info:
        f1 = teams_info["faction1"]
        if f1.get("name") and (team1_name == "Drużyna 1" or not team1_name):
            team1_name = f1.get("name")
        leader1_id = f1.get("leader") or ""
        team1_captain_id = leader1_id
        cap1_player = None
        for p in f1.get("roster", []):
            sid = str(p.get("game_player_id") or "")
            nick = str(p.get("nickname") or "").lower()
            av = p.get("avatar") or ""
            if sid:
                faction1_sids.add(sid)
                if av:
                    steam_to_avatar[sid] = av
            if nick:
                faction1_nicks.add(nick)
            p_id = p.get("player_id")
            if p_id and av and avatars is not None:
                avatars[p_id] = av
            if leader1_id and p_id == leader1_id:
                cap1_player = p

        if not cap1_player and f1.get("roster"):
            cap1_player = f1.get("roster")[0]
            if not team1_captain_id:
                team1_captain_id = cap1_player.get("player_id") or ""

        if cap1_player:
            team1_captain_avatar = cap1_player.get("avatar") or ""
            team1_captain_name = cap1_player.get("nickname") or ""

        if not team1_captain_avatar:
            team1_captain_avatar = f1.get("avatar") or ""

    if "faction2" in teams_info:
        f2 = teams_info["faction2"]
        if f2.get("name") and (team2_name == "Drużyna 2" or not team2_name):
            team2_name = f2.get("name")
        leader2_id = f2.get("leader") or ""
        team2_captain_id = leader2_id
        cap2_player = None
        for p in f2.get("roster", []):
            sid = str(p.get("game_player_id") or "")
            nick = str(p.get("nickname") or "").lower()
            av = p.get("avatar") or ""
            if sid:
                faction2_sids.add(sid)
                if av:
                    steam_to_avatar[sid] = av
            if nick:
                faction2_nicks.add(nick)
            p_id = p.get("player_id")
            if p_id and av and avatars is not None:
                avatars[p_id] = av
            if leader2_id and p_id == leader2_id:
                cap2_player = p

        if not cap2_player and f2.get("roster"):
            cap2_player = f2.get("roster")[0]
            if not team2_captain_id:
                team2_captain_id = cap2_player.get("player_id") or ""

        if cap2_player:
            team2_captain_avatar = cap2_player.get("avatar") or ""
            team2_captain_name = cap2_player.get("nickname") or ""

        if not team2_captain_avatar:
            team2_captain_avatar = f2.get("avatar") or ""

    if avatars:
        if team1_captain_id and not team1_captain_avatar:
            team1_captain_avatar = avatars.get(team1_captain_id, "")
        if team2_captain_id and not team2_captain_avatar:
            team2_captain_avatar = avatars.get(team2_captain_id, "")

    # Ekstrakcja oficjalnych MVP z Faceit API
    faceit_mvps_by_sid = {}
    faceit_mvps_by_nick = {}
    pid_to_sid = {}
    if match_info and "teams" in match_info:
        for f in match_info["teams"].values():
            for p in f.get("roster", []):
                pid = str(p.get("player_id") or "")
                sid = str(p.get("game_player_id") or "")
                nick = str(p.get("nickname") or "").lower()
                if pid and sid:
                    pid_to_sid[pid] = sid
                if nick and sid:
                    pid_to_sid[nick] = sid

    if match_stats and "rounds" in match_stats:
        for rnd in match_stats.get("rounds", []):
            for tm in rnd.get("teams", []):
                for pl in tm.get("players", []):
                    pid = str(pl.get("player_id") or "")
                    nick = str(pl.get("nickname") or "").lower()
                    try:
                        mvp_val = int(pl.get("player_stats", {}).get("MVPs", 0) or 0)
                    except (ValueError, TypeError):
                        mvp_val = 0

                    if pid and pid in pid_to_sid:
                        faceit_mvps_by_sid[pid_to_sid[pid]] = mvp_val
                    if nick:
                        faceit_mvps_by_nick[nick] = mvp_val
                        if nick in pid_to_sid:
                            faceit_mvps_by_sid[pid_to_sid[nick]] = mvp_val

    team1_players = []
    team2_players = []
    unassigned_players = []

    for p_stat in analysis_data["player_stats"]:
        sid = str(p_stat.get("steam_id", ""))
        nick = str(p_stat.get("persona_name", "")).lower()
        if sid in steam_to_avatar:
            p_stat["avatar"] = steam_to_avatar[sid]

        p_stat["mvps"] = faceit_mvps_by_sid.get(sid, faceit_mvps_by_nick.get(nick, 0))

        if sid in faction1_sids or (nick and nick in faction1_nicks):
            team1_players.append(p_stat)
        elif sid in faction2_sids or (nick and nick in faction2_nicks):
            team2_players.append(p_stat)
        else:
            unassigned_players.append(p_stat)

    for p_stat in unassigned_players:
        if len(team1_players) <= len(team2_players):
            team1_players.append(p_stat)
        else:
            team2_players.append(p_stat)

    # Sortowanie każdej drużyny po ClutchRating malejąco
    team1_players.sort(key=lambda x: x.get("clutchdata_rating", 0.0), reverse=True)
    team2_players.sort(key=lambda x: x.get("clutchdata_rating", 0.0), reverse=True)

    # If captain avatar still missing, try to get from first player avatar in team
    if not team1_captain_avatar and team1_players and team1_players[0].get("avatar"):
        team1_captain_avatar = team1_players[0].get("avatar")
    if not team2_captain_avatar and team2_players and team2_players[0].get("avatar"):
        team2_captain_avatar = team2_players[0].get("avatar")

    analysis_data["teams"] = [
        {
            "team_name": team1_name,
            "score": team1_score,
            "players": team1_players,
            "captain_avatar": team1_captain_avatar,
            "captain_name": team1_captain_name,
            "captain_id": team1_captain_id
        },
        {
            "team_name": team2_name,
            "score": team2_score,
            "players": team2_players,
            "captain_avatar": team2_captain_avatar,
            "captain_name": team2_captain_name,
            "captain_id": team2_captain_id
        }
    ]

    analysis_data["teams_meta"] = {
        "team1": {
            "name": team1_name,
            "captain_avatar": team1_captain_avatar,
            "captain_name": team1_captain_name,
            "score": team1_score
        },
        "team2": {
            "name": team2_name,
            "captain_avatar": team2_captain_avatar,
            "captain_name": team2_captain_name,
            "score": team2_score
        }
    }

    # Wzbogacenie szczegółów poszczególnych rund (składy drużyn, MVP, powód wygranej)
    team1_sids = set(str(p.get("steam_id", "")) for p in team1_players)
    team2_sids = set(str(p.get("steam_id", "")) for p in team2_players)
    team1_nicks = set(str(p.get("persona_name", "")).lower() for p in team1_players)
    team2_nicks = set(str(p.get("persona_name", "")).lower() for p in team2_players)

    rounds_list = analysis_data.get("rounds", [])
    for r in rounds_list:
        r_players = r.get("players", [])
        r_team1 = []
        r_team2 = []
        r_unassigned = []

        for rp in r_players:
            sid = str(rp.get("steam_id", ""))
            nick = str(rp.get("persona_name", "")).lower()
            if sid in steam_to_avatar:
                rp["avatar"] = steam_to_avatar[sid]
            elif not rp.get("avatar"):
                for ps in analysis_data.get("player_stats", []):
                    if str(ps.get("steam_id", "")) == sid and ps.get("avatar"):
                        rp["avatar"] = ps["avatar"]
                        break

            if sid in team1_sids or (nick and nick in team1_nicks):
                r_team1.append(rp)
            elif sid in team2_sids or (nick and nick in team2_nicks):
                r_team2.append(rp)
            else:
                r_unassigned.append(rp)

        for rp in r_unassigned:
            if len(r_team1) <= len(r_team2):
                r_team1.append(rp)
            else:
                r_team2.append(rp)

        r_team1.sort(key=lambda x: (x.get("impact", 0.0), x.get("kills", 0), x.get("damage_dealt", 0.0)), reverse=True)
        r_team2.sort(key=lambda x: (x.get("impact", 0.0), x.get("kills", 0), x.get("damage_dealt", 0.0)), reverse=True)

        team1_side = r_team1[0].get("side_played", "") if r_team1 else ("CT" if r.get("winning_side") == "CT" else "T")
        team2_side = r_team2[0].get("side_played", "") if r_team2 else ("T" if team1_side == "CT" else "CT")

        winning_side = r.get("winning_side", "")
        win_icon, win_text = format_win_reason(r.get("win_reason", ""), winning_side)

        all_r_players = r_players or (r_team1 + r_team2)
        mvp_p = max(all_r_players, key=lambda x: (x.get("impact", 0.0), x.get("kills", 0), x.get("damage_dealt", 0.0)), default=None)

        mvp_data = {
            "persona_name": mvp_p.get("persona_name", r.get("mvp") or "Nieznany") if mvp_p else (r.get("mvp") or "Nieznany"),
            "steam_id": mvp_p.get("steam_id", "") if mvp_p else "",
            "avatar": mvp_p.get("avatar", "") if mvp_p else "",
            "impact": mvp_p.get("impact", 0.0) if mvp_p else 0.0,
            "kills": mvp_p.get("kills", 0) if mvp_p else 0,
            "deaths": mvp_p.get("deaths", 0) if mvp_p else 0,
            "assists": mvp_p.get("assists", 0) if mvp_p else 0,
            "damage_dealt": int(mvp_p.get("damage_dealt", 0.0)) if mvp_p else 0,
            "utility_damage": int(mvp_p.get("utility_damage", 0.0)) if mvp_p else 0,
            "side_played": mvp_p.get("side_played", "") if mvp_p else ""
        }

        r["team1_players"] = r_team1
        r["team2_players"] = r_team2
        r["team1_side"] = team1_side
        r["team2_side"] = team2_side
        r["team1_won"] = (winning_side == team1_side)
        r["team2_won"] = (winning_side == team2_side)
        r["mvp_data"] = mvp_data
        r["win_reason_icon"] = win_icon
        r["win_reason_text"] = win_text
        r["duration_seconds"] = round(float(r.get("duration_seconds") or 0.0), 1)

    # Obliczenie MVP Całego Meczu (Match MVP)
    all_players = analysis_data.get("player_stats", [])
    match_mvp = None
    if all_players:
        match_mvp = max(all_players, key=lambda x: (x.get("clutchdata_rating", 0.0), x.get("kills", 0)), default=None)
        if match_mvp:
            mvp_sid = str(match_mvp.get("steam_id", ""))
            if mvp_sid in team1_sids:
                match_mvp["team_name"] = team1_name
            elif mvp_sid in team2_sids:
                match_mvp["team_name"] = team2_name
            else:
                match_mvp["team_name"] = ""

    # Wyznaczenie zwycięzcy meczu
    t1_score_int = None
    t2_score_int = None
    try:
        if team1_score:
            t1_score_int = int(team1_score)
        if team2_score:
            t2_score_int = int(team2_score)
    except (ValueError, TypeError):
        pass

    winner_team_name = None
    if t1_score_int is not None and t2_score_int is not None:
        if t1_score_int > t2_score_int:
            winner_team_name = team1_name
        elif t2_score_int > t1_score_int:
            winner_team_name = team2_name

    analysis_data["match_mvp"] = match_mvp
    analysis_data["winner_meta"] = {
        "winner_name": winner_team_name,
        "team1_score": team1_score,
        "team2_score": team2_score,
        "score_display": f"{team1_score} - {team2_score}" if (team1_score and team2_score) else ""
    }

    return analysis_data


def verify_demo_matches_roster(match_info: Dict[str, Any], parsed_data: Dict[str, Any]):
    """
    Weryfikuje, czy gracze w sparsowanym pliku demo zgadzają się ze składem meczu Faceit.
    Zapobiega wgraniu innego dema z podmienioną nazwą pliku.
    """
    expected_sids = set()
    teams = match_info.get("teams", {})
    for f_key in ("faction1", "faction2"):
        faction = teams.get(f_key, {})
        if isinstance(faction, dict):
            for p in faction.get("roster", []):
                sid = str(p.get("game_player_id") or "").strip()
                if sid:
                    expected_sids.add(sid)

    if not expected_sids:
        return

    df_match_stats = parsed_data.get("match_statistics")
    if df_match_stats is not None and not df_match_stats.empty and "steam_id" in df_match_stats.columns:
        demo_sids = set(str(s).strip() for s in df_match_stats["steam_id"].dropna() if str(s).strip() and str(s).strip() != "0")
        matching = expected_sids.intersection(demo_sids)
        if not matching:
            raise ValueError(
                "Zawartość powtórki nie zgadza się ze składem tego meczu Faceit "
                "(żaden z graczy z listy uczestników nie został odnaleziony w pliku demo)."
            )





async def analyze_uploaded_demo(
    db: AsyncSession,
    match_id: str,
    faceit_api_key: str,
    file_bytes: bytes,
    filename: str
) -> Dict[str, Any]:
    """
    Przetwarza przesłany przez użytkownika plik dema (.dem, .dem.zst, .gz):
    1. Sprawdza zgodność nazwy pliku z match_id
    2. Pobiera metadane meczu z Faceit API
    3. Rozpakowuje plik dema
    4. Analizuje powtórkę za pomocą Demo_parser i weryfikuje skład
    5. Zapisuje dane w bazie i zwraca przetworzone statystyki
    """
    if not faceit_api_key:
        return {"success": False, "error": "Brak klucza API Faceit."}

    # Weryfikacja nazwy pliku
    clean_match_id = match_id.removeprefix("1-").lower()
    if clean_match_id not in filename.lower() and match_id.lower() not in filename.lower():
        return {
            "success": False,
            "error": f"Przesłany plik '{filename}' nie pasuje do tego meczu. Upewnij się, że wgrywasz oryginalny plik powtórki pobrany dla meczu {match_id}."
        }

    headers = {
        "Authorization": f"Bearer {faceit_api_key}",
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        info_resp = await client.get(f"https://open.faceit.com/data/v4/matches/{match_id}", headers=headers)
        if info_resp.status_code != 200:
            return {"success": False, "error": f"Nie udało się pobrać szczegółów meczu z Faceit (Kod: {info_resp.status_code})"}
        match_info = info_resp.json()

    os.makedirs(TEMP_DEMOS_DIR, exist_ok=True)
    ext = ".dem"
    low_name = filename.lower()
    if low_name.endswith(".zst"):
        ext = ".zst"
    elif low_name.endswith(".gz"):
        ext = ".gz"

    temp_compressed = os.path.join(TEMP_DEMOS_DIR, f"{match_id}_uploaded{ext}")
    final_dem_path = os.path.join(TEMP_DEMOS_DIR, f"{match_id}.dem")

    try:
        with open(temp_compressed, "wb") as f:
            f.write(file_bytes)

        # Dekompresja
        if ext == ".zst":
            dctx = zstd.ZstdDecompressor()
            with open(temp_compressed, "rb") as ifh, open(final_dem_path, "wb") as ofh:
                dctx.copy_stream(ifh, ofh)
        elif ext == ".gz":
            with gzip.open(temp_compressed, "rb") as ifh, open(final_dem_path, "wb") as ofh:
                shutil.copyfileobj(ifh, ofh)
        else:
            if temp_compressed != final_dem_path:
                shutil.copyfile(temp_compressed, final_dem_path)

        # Parsowanie dema
        parsed_data = await asyncio.to_thread(parse_demo_to_dataframes, final_dem_path, 1)

        # Weryfikacja zgodności graczy z dema ze składem meczu
        verify_demo_matches_roster(match_info, parsed_data)

        # Zapis do bazy danych
        await save_analyzed_demo_data(db, match_id, match_info, parsed_data)

        # Pobranie zapisanego wyniku
        analyzed_data = await get_full_analyzed_match_data(db, match_id)
        if analyzed_data:
            enrich_analyzed_teams(analyzed_data, match_info)

        return {
            "success": True,
            "message": "Mecz został pomyślnie przeanalizowany z wgranego pliku dema!",
            "data": analyzed_data
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Błąd podczas analizy wgranego pliku dema: {str(e)}"
        }
    finally:
        if os.path.exists(temp_compressed) and temp_compressed != final_dem_path:
            try:
                os.remove(temp_compressed)
            except Exception:
                pass
        if os.path.exists(final_dem_path):
            try:
                os.remove(final_dem_path)
            except Exception:
                pass
