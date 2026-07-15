from fastapi import HTTPException
import httpx
import re

STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"

async def load_steam_data(client,api_key, steam_id):
    player_summary = None
    stats_data = None
    summary_url = f"http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={api_key}&steamids={steam_id}"
    summary_resp = await client.get(summary_url)
    if summary_resp.status_code == 200:
        data = summary_resp.json()
        players = data.get("response", {}).get("players", [])
        if players:
            player_summary = players[0]
    
    # Get CS2 stats
    stats_url = f"http://api.steampowered.com/ISteamUserStats/GetUserStatsForGame/v0002/?appid=730&key={api_key}&steamid={steam_id}"
    stats_resp = await client.get(stats_url)
    if stats_resp.status_code == 200:
        stats_data = stats_resp.json().get("playerstats", {}).get("stats", [])

    return player_summary, stats_data
async def hours_counter(client, api_key, steam_id):
    hours_played = 0
    if api_key and api_key != "your_steam_api_key_here":
        try:
            async with httpx.AsyncClient() as client:
                owned_games_url = f"http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={api_key}&steamid={steam_id}&format=json"
                owned_resp = await client.get(owned_games_url)
                if owned_resp.status_code == 200:
                    games = owned_resp.json().get("response", {}).get("games", [])
                    cs_game = next((g for g in games if g.get("appid") == 730), None)
                    if cs_game:
                        hours_played = round(cs_game.get("playtime_forever", 0) / 60)
                        return hours_played
        except Exception:
            pass

async def validate_steam_login(params: dict):
    if params.get("openid.mode") != "id_res":
        raise HTTPException(status_code=400, detail="Invalid OpenID mode")
        
    # Prepare validation request
    validation_params = params.copy()
    validation_params["openid.mode"] = "check_authentication"
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(STEAM_OPENID_URL, data=validation_params)
        
    if "is_valid:true" not in resp.text:
        raise HTTPException(status_code=400, detail="Steam OpenID validation failed")
        
    # Extract SteamID64 from claimed_id
    claimed_id = params.get("openid.claimed_id", "")
    match = re.search(r"https://steamcommunity.com/openid/id/(\d+)", claimed_id)
    if not match:
        raise HTTPException(status_code=400, detail="Could not extract SteamID")
        
    steam_id = match.group(1)

    return steam_id


async def resolve_steam_vanity_url(api_key: str, vanity_name: str):                                                                                                                                                                                 
        url = f"http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/?key={api_key}&vanityurl={vanity_name}"                                                                                                                                   
                                                                                                                                                                                                                                                        
        async with httpx.AsyncClient() as client:                                                                                                                                                                                                       
            response = await client.get(url)                                                                                                                                                                                                            
                                                                                                                                                                                                                                                        
        if response.status_code == 200:                                                                                                                                                                                                                 
            data = response.json()                                                                                                                                                                                                                      
            if data.get("response", {}).get("success") == 1:                                                                                                                                                                                                                                                                                                                                                                                           
                return data["response"]["steamid"]                                                                                                                                                                                                      
                                                                                                                                                                                                                                                        
        # Zwróć None, jeśli coś poszło nie tak                                                                                                                                                                                                          
        return None                     