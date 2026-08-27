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

async def get_presigned_download_url(resource_url: str, match_id: str) -> str:
    """
    Odpytuje wewnętrzny endpoint Faceit o bezpośredni, podpisany link S3 (Backblaze).
    Wymaga nagłówków przeglądarkowych oraz ciasteczek sesyjnych (FACEIT_COOKIES).
    """
    api_url = "https://www.faceit.com/api/download/v2/demos/download-url"
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        "content-type": "application/json",
        "faceit-referer": "web-next",
        "origin": "https://www.faceit.com",
        "referer": f"https://www.faceit.com/en/cs2/room/{match_id}",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    }

    cookies = os.getenv("FACEIT_COOKIES")
    if cookies:
        headers["cookie"] = cookies

    payload = {"resource_url": resource_url}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(api_url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    payload_data = data.get("payload")
                    if isinstance(payload_data, dict):
                        signed_url = payload_data.get("download_url") or payload_data.get("url")
                        if signed_url:
                            return signed_url
                    elif isinstance(payload_data, str) and payload_data.startswith("http"):
                        return payload_data
                    
                    fallback_url = data.get("download_url") or data.get("url")
                    if fallback_url:
                        return fallback_url
    except Exception:
        pass

    return resource_url


async def download_and_extract_demo(demo_url: str, match_id: str) -> str:
    """
    Pobiera plik demo ze wskazanego adresu URL i wypakowuje go do pliku .dem.
    Obsługuje kompresję Zstandard (.zst), Gzip (.gz) oraz zwykłe pliki .dem.
    """
    os.makedirs(TEMP_DEMOS_DIR, exist_ok=True)
    
    # Wyczyszczenie adresu URL jeśli Faceit zwrócił listę
    if isinstance(demo_url, list):
        if not demo_url:
            raise ValueError("Brak adresu URL do dema.")
        demo_url = demo_url[0]

    # 1. Uzyskanie podpisanego linku S3, jeśli podany URL to wewnętrzny Faceit CDN
    effective_url = demo_url
    if "faceit-cdn.net" in demo_url or "backblaze" in demo_url:
        effective_url = await get_presigned_download_url(demo_url, match_id)

    # 2. Określenie rozszerzenia pliku
    url_check = demo_url.lower().split("?")[0]
    if not (url_check.endswith(".zst") or url_check.endswith(".gz") or url_check.endswith(".dem")):
        url_check = effective_url.lower().split("?")[0]

    if url_check.endswith(".zst"):
        ext = ".zst"
    elif url_check.endswith(".gz"):
        ext = ".gz"
    else:
        ext = ".dem"

    temp_compressed = os.path.join(TEMP_DEMOS_DIR, f"{match_id}_compressed{ext}")
    final_dem_path = os.path.join(TEMP_DEMOS_DIR, f"{match_id}.dem")

    # 3. Pobieranie pliku demo
    async with httpx.AsyncClient(follow_redirects=True, timeout=300.0) as client:
        async with client.stream("GET", effective_url) as response:
            if response.status_code != 200:
                raise RuntimeError(f"Błąd pobierania dema z CDN (Status: {response.status_code})")
            
            with open(temp_compressed, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)

    # 4. Dekompresja pliku
    try:
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
    finally:
        # Usuwamy plik skompresowany po dekompresji
        if os.path.exists(temp_compressed) and temp_compressed != final_dem_path:
            try:
                os.remove(temp_compressed)
            except Exception:
                pass

    return final_dem_path


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

    team1_players = []
    team2_players = []
    unassigned_players = []

    for p_stat in analysis_data["player_stats"]:
        sid = str(p_stat.get("steam_id", ""))
        nick = str(p_stat.get("persona_name", "")).lower()
        if sid in steam_to_avatar:
            p_stat["avatar"] = steam_to_avatar[sid]

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
    return analysis_data


async def analyze_match_demo(db: AsyncSession, match_id: str, faceit_api_key: str) -> Dict[str, Any]:
    """
    Główna funkcja orkiestrująca analizę dema:
    1. Pobranie metadanych meczu i URL powtórki z Faceit API
    2. Pobranie i dekompresja pliku powtórki (.dem)
    3. Analiza zdarzeń i statystyk za pomocą Demo_parser (demoparser2)
    4. Zapis szczegółowych statystyk, ratingu i rund do bazy danych
    5. Sprzątanie plików tymczasowych
    """
    if not faceit_api_key:
        return {"success": False, "error": "Brak klucza API Faceit."}

    headers = {
        "Authorization": f"Bearer {faceit_api_key}",
        "Accept": "application/json"
    }

    # 1. Pobranie danych o meczu z Faceit
    async with httpx.AsyncClient() as client:
        info_resp = await client.get(f"https://open.faceit.com/data/v4/matches/{match_id}", headers=headers)
        if info_resp.status_code != 200:
            return {"success": False, "error": f"Nie udało się pobrać szczegółów meczu z Faceit (Kod: {info_resp.status_code})"}
        match_info = info_resp.json()

    # Sprawdzenie czy demo jest dostępne
    demo_urls = match_info.get("demo_url")
    if not demo_urls:
        return {
            "success": False, 
            "error": "Powtórka (demo) dla tego meczu nie jest jeszcze dostępna na serwerach Faceit lub wygasła."
        }

    demo_url = demo_urls[0] if isinstance(demo_urls, list) else demo_urls

    extracted_dem_path = None
    try:
        # 2. Pobranie i rozpakowanie dema
        extracted_dem_path = await download_and_extract_demo(demo_url, match_id)

        # 3. Parsowanie dema (wywołanie synchronicznego parsera w wątku roboczym)
        parsed_data = await asyncio.to_thread(parse_demo_to_dataframes, extracted_dem_path, 1)

        # 4. Zapis do bazy danych
        await save_analyzed_demo_data(db, match_id, match_info, parsed_data)

        # 5. Pobranie zapisanego wyniku
        analyzed_data = await get_full_analyzed_match_data(db, match_id)
        if analyzed_data:
            enrich_analyzed_teams(analyzed_data, match_info)

        return {
            "success": True,
            "message": "Mecz został pomyślnie przeanalizowany przez ClutchData+!",
            "data": analyzed_data
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Błąd podczas analizy powtórki meczu: {str(e)}"
        }
    finally:
        # 6. Czyszczenie plików tymczasowych
        if extracted_dem_path and os.path.exists(extracted_dem_path):
            try:
                os.remove(extracted_dem_path)
            except Exception:
                pass
