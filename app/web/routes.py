import os
import httpx
import asyncio
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from app.services.steam_stats import load_steam_data, hours_counter, validate_steam_login, resolve_steam_vanity_url
from app.services.faceit_stats import load_faceit_data, fetch_match_stats, get_match_details, load_faceit_data_by_id, faceit_steam_id_validation
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.crud import save_faceit_elo

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"
STEAM_API_KEY = os.getenv("STEAM_API_KEY")

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Check if user is already logged in
    steam_id = request.session.get("steam_id")
    if steam_id:
        return RedirectResponse(url=f"/player/{steam_id}")
    return templates.TemplateResponse(request=request, name="index.html")

@router.get("/auth/steam/login")
async def steam_login(request: Request):
    # Determine the return URL based on the request
    # In production, this should be a hardcoded HTTPS url
    base_url = str(request.base_url).rstrip("/")
    return_to = f"{base_url}/auth/steam/callback"
    realm = base_url
    
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": realm,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    
    url = f"{STEAM_OPENID_URL}?{httpx.QueryParams(params)}"
    return RedirectResponse(url=url)

@router.get("/auth/steam/callback")
async def steam_callback(request: Request):
    # Get all query parameters returned by Steam
    params = dict(request.query_params)
    
    steam_id = await validate_steam_login(params)
    
    # Store in session
    request.session["steam_id"] = steam_id
    request.session["logged_steam_id"] = steam_id  # Store the logged-in Steam ID for reference
    
    return RedirectResponse(url=f"/player/{steam_id}")

@router.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@router.get("/player/{steam_id}", response_class=HTMLResponse)
async def dashboard(request: Request, steam_id: str, db: AsyncSession = Depends(get_db)):
    logged_steam_id = request.session.get("steam_id")
    if not logged_steam_id:
        return RedirectResponse(url="/")
        
    # Fetch user stats from Steam API
    stats_data = None
    player_summary = None
    faceit_data = None
    faceit_stats = None
    faceit_history = None
    
    api_key = os.getenv("STEAM_API_KEY")
    faceit_api_key = os.getenv("FACEIT_API_KEY")

    async with httpx.AsyncClient() as client:
        # 1. Fetch Steam Data
        if api_key and api_key != "your_steam_api_key_here":
            player_summary, stats_data = await load_steam_data(client, api_key, steam_id)
            request.session["logged_player_summary"], _ = await load_steam_data(client, api_key, request.session.get("logged_steam_id"))
        # 2. Fetch FACEIT Data
        if faceit_api_key:
            headers = {
                "Authorization": f"Bearer {faceit_api_key}",
                "Accept": "application/json"
            }
            faceit_data, faceit_stats, base_history = await load_faceit_data(headers, client,  steam_id)
            tasks = [fetch_match_stats(client, m, headers, faceit_data) for m in base_history]
            faceit_history = await asyncio.gather(*tasks)
            
            # Zapisywanie do bazy
            if faceit_data and faceit_data.get("games", {}).get("cs2"):
                current_elo = faceit_data["games"]["cs2"].get("faceit_elo")
                if current_elo:
                    persona = faceit_data.get("nickname", "Unknown")
                    if player_summary:
                        persona = player_summary.get("personaname", persona)
                    await save_faceit_elo(db, steam_id, persona, current_elo)

    
    hours_played = await hours_counter(client, api_key, steam_id)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "logged_player_summary": request.session.get("logged_player_summary"),
            "steam_id": steam_id,
            "player_summary": player_summary,
            "stats": stats_data,
            "faceit_data": faceit_data,
            "faceit_stats": faceit_stats,
            "faceit_history": faceit_history,
            "hours_played": hours_played,
            "api_key_missing": not api_key or api_key == "your_steam_api_key_here"
        }
    )



@router.get("/faceit_search/{player_id}", response_class=RedirectResponse)
async def faceit_search(request: Request, player_id: str):
    faceit_api_key = os.getenv("FACEIT_API_KEY")
    faceit_data = None
    

    if faceit_api_key:
        headers = {
            "Authorization": f"Bearer {faceit_api_key}",
            "Accept": "application/json"
        }
        async with httpx.AsyncClient() as client:
            faceit_data, _ , _ = await load_faceit_data_by_id(headers, client, player_id)
    steam_id = None
    if faceit_data:
        steam_id = await faceit_steam_id_validation(faceit_data)
    

    return RedirectResponse(url=f"/player/{steam_id}",status_code=302)

@router.get("/match/{match_id}", response_class=HTMLResponse)
async def match_details(request: Request, match_id: str):
    steam_id = request.session.get("steam_id")
    if not steam_id:
        return RedirectResponse(url="/")

   
    api_key = os.getenv("STEAM_API_KEY")
    player_summary = None
    if api_key and api_key != "your_steam_api_key_here":
        async with httpx.AsyncClient() as client:
            player_summary, _ = await load_steam_data(client, api_key, steam_id)

    faceit_api_key = os.getenv("FACEIT_API_KEY")
    match_info, match_stats = {}, {}
    
    if faceit_api_key:
        headers = {
            "Authorization": f"Bearer {faceit_api_key}",
            "Accept": "application/json"
        }
        async with httpx.AsyncClient() as client:
            match_info, match_stats = await get_match_details(client, headers, match_id)

    avatars = {}
    if match_info and "teams" in match_info:
        for faction_name, faction_data in match_info.get("teams", {}).items():
            for player in faction_data.get("roster", []):
                p_id = player.get("player_id")
                if p_id:
                    avatars[p_id] = player.get("avatar", "")

    return templates.TemplateResponse(
        request=request,
        name="match.html",
        context={
            "logged_player_summary": request.session.get("logged_player_summary"),
            "steam_id": steam_id,
            "player_summary": player_summary,
            "match_info": match_info,
            "match_stats": match_stats,
            "match_id": match_id,
            "avatars": avatars
        }
    )

@router.post("/search", response_class=RedirectResponse)
async def search_player(request: Request, steam_url: str = Form(...)):
    if "https://steamcommunity.com/profiles/" in steam_url:
        steam_url = steam_url.removeprefix("https://steamcommunity.com/profiles/")
    elif "https://steamcommunity.com/id/" in steam_url:
        steam_url = steam_url.removeprefix("https://steamcommunity.com/id/")
        
        
    steam_id_or_vanity = steam_url.strip('/')
        
    if steam_id_or_vanity.isdigit() and len(steam_id_or_vanity) == 17:
        steam_id = steam_id_or_vanity
    else:
        steam_id = await resolve_steam_vanity_url(api_key=os.getenv("STEAM_API_KEY"), vanity_name=steam_id_or_vanity)

    if not steam_id:
        referer = request.headers.get("referer", "/")
        if "?" in referer:
            referer = referer.split("?")[0]
        return RedirectResponse(url=f"{referer}?error=Invalid+Steam+profile", status_code=302)
    
    return RedirectResponse(url=f"/player/{steam_id}", status_code=302)

@router.get("/player/{steam_id}/stats", response_class=HTMLResponse)
async def player_stats(request: Request, steam_id: str):
    logged_steam_id = request.session.get("steam_id")
    if not logged_steam_id:
        return RedirectResponse(url="/")

    api_key = os.getenv("STEAM_API_KEY")
    faceit_api_key = os.getenv("FACEIT_API_KEY")
    player_summary = None
    faceit_data = None
    faceit_stats = None
    map_segments = []
    weapon_stats = []

    async with httpx.AsyncClient() as client:
        # Steam data
        if api_key and api_key != "your_steam_api_key_here":
            player_summary, raw_stats = await load_steam_data(client, api_key, steam_id)

            # Parse weapon stats from Steam
            WEAPONS = [
                ("ak47", "AK-47"), ("m4a1", "M4A1-S"), ("m4a1_silencer", "M4A4"),
                ("awp", "AWP"), ("deagle", "Desert Eagle"), ("glock", "Glock-18"),
                ("usp_silencer", "USP-S"), ("hkp2000", "P2000"), ("p250", "P250"),
                ("cz75a", "CZ75-Auto"), ("tec9", "Tec-9"), ("fiveseven", "Five-SeveN"),
                ("revolver", "R8 Revolver"), ("elite", "Dual Berettas"),
                ("famas", "FAMAS"), ("galilar", "Galil AR"), ("aug", "AUG"),
                ("sg556", "SG 553"), ("ssg08", "SSG 08"), ("g3sg1", "G3SG1"),
                ("scar20", "SCAR-20"), ("mp9", "MP9"), ("mac10", "MAC-10"),
                ("mp7", "MP7"), ("mp5sd", "MP5-SD"), ("ump45", "UMP-45"),
                ("p90", "P90"), ("bizon", "PP-Bizon"), ("m249", "M249"),
                ("negev", "Negev"), ("nova", "Nova"), ("mag7", "MAG-7"),
                ("sawedoff", "Sawed-Off"), ("xm1014", "XM1014"), ("m3", "M3"),
                ("knife", "Nóż"), ("taser", "Zeus x27"),
            ]
            
            if raw_stats:
                stats_lookup = {s["name"]: s["value"] for s in raw_stats}
                for key, display_name in WEAPONS:
                    kills = stats_lookup.get(f"total_kills_{key}", 0)
                    shots = stats_lookup.get(f"total_shots_{key}", 0)
                    hits = stats_lookup.get(f"total_hits_{key}", 0)
                    if kills > 0 or shots > 0:
                        accuracy = round((hits / shots * 100), 1) if shots > 0 else 0
                        weapon_stats.append({
                            "key": key,
                            "name": display_name,
                            "kills": kills,
                            "shots": shots,
                            "hits": hits,
                            "accuracy": accuracy,
                        })
                # Sort by kills desc
                weapon_stats.sort(key=lambda x: x["kills"], reverse=True)

        # Faceit data
        if faceit_api_key:
            headers = {
                "Authorization": f"Bearer {faceit_api_key}",
                "Accept": "application/json"
            }
            faceit_data, faceit_stats, _ = await load_faceit_data(headers, client, steam_id)

            # Extract map segments
            if faceit_stats:
                segments = faceit_stats.get("segments", [])
                for seg in segments:
                    if seg.get("type") == "Map":
                        label = seg.get("label", "")
                        s = seg.get("stats", {})
                        map_segments.append({
                            "map": label,
                            "matches": int(s.get("Matches", 0)),
                            "wins": int(s.get("Wins", 0)),
                            "win_rate": float(s.get("Win Rate %", 0)),
                            "kills": int(s.get("Kills", 0)),
                            "deaths": int(s.get("Deaths", 0)),
                            "assists": int(s.get("Assists", 0)),
                            "kd": float(s.get("Average K/D Ratio", 0)),
                            "kr": float(s.get("Average K/R Ratio", 0)),
                            "adr": float(s.get("ADR", 0)),
                            "hs_pct": float(s.get("Average Headshots %", 0)),
                            "rounds": int(s.get("Rounds", 0)),
                            "mvps": int(s.get("MVPs", 0)),
                            "triple_kills": int(s.get("Triple Kills", 0)),
                            "quadro_kills": int(s.get("Quadro Kills", 0)),
                            "penta_kills": int(s.get("Penta Kills", 0)),
                            # Clutch stats
                            "entry_count": int(s.get("Total Entry Count", 0)),
                            "entry_wins": int(s.get("Total Entry Wins", 0)),
                            "entry_success_rate": float(s.get("Entry Success Rate", 0)),
                            "v1_count": int(s.get("Total 1v1 Count", 0)),
                            "v1_wins": int(s.get("Total 1v1 Wins", 0)),
                            "v1_rate": float(s.get("1v1 Win Rate", 0)),
                            "v2_count": int(s.get("Total 1v2 Count", 0)),
                            "v2_wins": int(s.get("Total 1v2 Wins", 0)),
                            "v2_rate": float(s.get("1v2 Win Rate", 0)),
                            "v3_count": int(s.get("Total 1v3 Count", 0)),
                            "v3_wins": int(s.get("Total 1v3 Wins", 0)),
                            "v3_rate": float(s.get("1v3 Win Rate", 0)),
                            "v4_count": int(s.get("Total 1v4 Count", 0)),
                            "v4_wins": int(s.get("Total 1v4 Wins", 0)),
                            "v4_rate": float(s.get("1v4 Win Rate", 0)),
                            "v5_count": int(s.get("Total 1v5 Count", 0)),
                            "v5_wins": int(s.get("Total 1v5 Wins", 0)),
                            "v5_rate": float(s.get("1v5 Win Rate", 0)),
                        })
                # Sort by matches desc
                map_segments.sort(key=lambda x: x["matches"], reverse=True)

    # Lifetime faceit stats
    faceit_lifetime = faceit_stats.get("lifetime", {}) if faceit_stats else {}

    return templates.TemplateResponse(
        request=request,
        name="stats.html",
        context={
            "logged_player_summary": request.session.get("logged_player_summary"),
            "steam_id": steam_id,
            "player_summary": player_summary,
            "faceit_data": faceit_data,
            "faceit_lifetime": faceit_lifetime,
            "map_segments": map_segments,
            "weapon_stats": weapon_stats,
        }
    )
