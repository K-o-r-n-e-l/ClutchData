import os
import httpx
import asyncio
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from app.services.steam_stats import load_steam_data, hours_counter, validate_steam_login, resolve_steam_vanity_url
from app.services.faceit_stats import load_faceit_data, fetch_match_stats, get_match_details, load_faceit_data_by_id, faceit_steam_id_validation

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"
STEAM_API_KEY = os.getenv("STEAM_API_KEY")

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Check if user is already logged in
    steam_id = request.session.get("steam_id")
    if steam_id:
        return RedirectResponse(url="/dashboard")
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
    
    return RedirectResponse(url="/dashboard")

@router.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    steam_id = request.session.get("steam_id")
    if not steam_id:
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

    # Get hours played from Steam
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

@router.get("/player/{player_id}", response_class=HTMLResponse)
async def player_dashboard(request: Request, player_id: str):
    faceit_api_key = os.getenv("FACEIT_API_KEY")
    faceit_data = None
    faceit_stats = None
    faceit_history = None

    if faceit_api_key:
        headers = {
            "Authorization": f"Bearer {faceit_api_key}",
            "Accept": "application/json"
        }
        async with httpx.AsyncClient() as client:
            faceit_data, faceit_stats, base_history = await load_faceit_data_by_id(headers, client, player_id)
            if faceit_data:
                tasks = [fetch_match_stats(client, m, headers, faceit_data) for m in base_history]
                faceit_history = await asyncio.gather(*tasks)

    steam_id = None
    if faceit_data:
        steam_id = await faceit_steam_id_validation(faceit_data)
    
    player_summary = None
    stats_data = None
    hours_played = None
    api_key = os.getenv("STEAM_API_KEY")
    
    if steam_id and api_key and api_key != "your_steam_api_key_here":
        async with httpx.AsyncClient() as client:
            player_summary, stats_data = await load_steam_data(client, api_key, steam_id)
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
@router.get("/match/{match_id}", response_class=HTMLResponse)
async def match_details(request: Request, match_id: str):
    steam_id = request.session.get("steam_id")
    if not steam_id:
        return RedirectResponse(url="/")

    # Fetch user stats from Steam API for the navbar
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
    steam_id = steam_url.removeprefix("https://steamcommunity.com/profiles/")
    steam_id = steam_id.strip("/")
    if not steam_id.isdigit() or not len(steam_id) == 17:
        steam_id = await resolve_steam_vanity_url(api_key=STEAM_API_KEY, vanity_name=steam_id)


    return RedirectResponse(url=f"/player/{steam_id}", status_code=302)    