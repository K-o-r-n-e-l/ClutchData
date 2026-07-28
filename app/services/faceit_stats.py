import datetime
async def load_faceit_data(headers, client, steam_id, offset=0, limit=10):
    
    # 2a. Get Faceit Player Info via SteamID
    # Note: We use game_player_id parameter to find the user by their steam64 id
    faceit_player_url = f"https://open.faceit.com/data/v4/players?game=cs2&game_player_id={steam_id}"
    faceit_resp = await client.get(faceit_player_url, headers=headers)
    
    faceit_data = None
    faceit_stats = None
    base_history = []
    
    if faceit_resp.status_code == 200:
        faceit_data = faceit_resp.json()
        faceit_player_id = faceit_data.get("player_id")
        
        # 2b. Get Faceit Player Stats for CS2
        faceit_stats_url = f"https://open.faceit.com/data/v4/players/{faceit_player_id}/stats/cs2"
        stats_resp = await client.get(faceit_stats_url, headers=headers)
        if stats_resp.status_code == 200:
            faceit_stats = stats_resp.json()
            
        # 2c. Get Faceit Match History
        faceit_history_url = f"https://open.faceit.com/data/v4/players/{faceit_player_id}/history?game=cs2&offset={offset}&limit={limit}"
        history_resp = await client.get(faceit_history_url, headers=headers)
        if history_resp.status_code == 200:
            base_history = history_resp.json().get("items", [])

    return faceit_data, faceit_stats, base_history


async def fetch_match_stats(c, match, headers, faceit_data):
                        faceit_player_id = faceit_data.get("player_id")
                        match_id = match.get("match_id")
                        m_stats_url = f"https://open.faceit.com/data/v4/matches/{match_id}/stats"
                        m_resp = await c.get(m_stats_url, headers=headers)
                        
                        m_data = match.copy()
                        m_data["player_stats"] = {}
                        if "finished_at" in m_data:
                            try:
                                m_data["finished_at_str"] = datetime.datetime.fromtimestamp(m_data["finished_at"]).strftime('%Y-%m-%d')
                            except Exception:
                                m_data["finished_at_str"] = str(m_data["finished_at"])
                        
                        if m_resp.status_code == 200:
                            stats_json = m_resp.json()
                            rounds = stats_json.get("rounds", [])
                            if rounds:
                                m_data["map"] = rounds[0].get("round_stats", {}).get("Map", "N/A")
                                teams = rounds[0].get("teams", [])
                                for team in teams:
                                    for player in team.get("players", []):
                                        if player.get("player_id") == faceit_data.get("player_id"):
                                            m_data["player_stats"] = player.get("player_stats", {})
                                            break
                        return m_data

async def get_match_details(client, headers, match_id):
    info_url = f"https://open.faceit.com/data/v4/matches/{match_id}"
    info_resp = await client.get(info_url, headers=headers)
    match_info = info_resp.json() if info_resp.status_code == 200 else {}
    
    stats_url = f"https://open.faceit.com/data/v4/matches/{match_id}/stats"
    stats_resp = await client.get(stats_url, headers=headers)
    match_stats = stats_resp.json() if stats_resp.status_code == 200 else {}
    
    return match_info, match_stats

async def load_faceit_data_by_id(headers, client, faceit_player_id):
    faceit_player_url = f"https://open.faceit.com/data/v4/players/{faceit_player_id}"
    faceit_resp = await client.get(faceit_player_url, headers=headers)
    
    faceit_data = None
    faceit_stats = None
    base_history = []

    if faceit_resp.status_code == 200:
        faceit_data = faceit_resp.json()
        
        faceit_stats_url = f"https://open.faceit.com/data/v4/players/{faceit_player_id}/stats/cs2"
        stats_resp = await client.get(faceit_stats_url, headers=headers)
        if stats_resp.status_code == 200:
            faceit_stats = stats_resp.json()
            
        faceit_history_url = f"https://open.faceit.com/data/v4/players/{faceit_player_id}/history?game=cs2&offset=0&limit=10"
        history_resp = await client.get(faceit_history_url, headers=headers)
        if history_resp.status_code == 200:
            base_history = history_resp.json().get("items", [])

    return faceit_data, faceit_stats, base_history



async def faceit_steam_id_validation(faceit_data):
    platforms = faceit_data.get("platforms") or {}
    games = faceit_data.get("games") or {}
    
    steam_id = (
            faceit_data.get("steam_id_64") or 
            platforms.get("steam") or 
            (games.get("cs2") or {}).get("game_player_id") or
            (games.get("csgo") or {}).get("game_player_id")
        )

    if steam_id and steam_id.startswith("STEAM_"):
        try:
            parts = steam_id.split(":")
            y = int(parts[1])
            z = int(parts[2])
            steam_id = str(76561197960265728 + (z * 2) + y)
        except Exception:
            pass
    
    return steam_id