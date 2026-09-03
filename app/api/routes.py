import os
import httpx
import asyncio
from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.schemas.player import PlayerStatsResponse
from app.services.faceit_stats import load_faceit_data, fetch_match_stats
from app.services.demo_service import analyze_uploaded_demo
from app.db.session import get_db
from app.db.crud import get_player_by_steam_id, player_ratings_dashboard

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/api")

@router.get("/player/{steam_id}/history", response_class=HTMLResponse)
async def get_player_history(
    request: Request, 
    steam_id: str, 
    offset: int = 10, 
    db: AsyncSession = Depends(get_db)
):
    faceit_api_key = os.getenv("FACEIT_API_KEY")
    if not faceit_api_key:
        return HTMLResponse("")
        
    headers = {
        "Authorization": f"Bearer {faceit_api_key}",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        faceit_data, _, base_history = await load_faceit_data(headers, client, steam_id, offset=offset, limit=10)
        
        if not base_history:
            return HTMLResponse("")
            
        tasks = [fetch_match_stats(client, m, headers, faceit_data) for m in base_history]
        faceit_history = await asyncio.gather(*tasks)
        
    player_ratings = await player_ratings_dashboard(db, steam_id)
        
    return templates.TemplateResponse(
        request=request,
        name="_match_rows.html",
        context={
            "faceit_history": faceit_history,
            "player_ratings": player_ratings
        }
    )

@router.post("/match/{match_id}/upload-demo")
async def api_upload_demo(
    request: Request,
    match_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    logged_steam_id = request.session.get("logged_steam_id") or request.session.get("steam_id")
    if not logged_steam_id:
        return JSONResponse(status_code=401, content={"success": False, "error": "Musisz być zalogowany, aby analizować mecze."})

    player_db = await get_player_by_steam_id(db, logged_steam_id)
    clutchdata_plus = getattr(player_db, 'clutchdata_plus', False) if player_db else False
    if not clutchdata_plus:
        return JSONResponse(status_code=403, content={"success": False, "error": "Funkcja wymaga aktywnej subskrypcji ClutchData+."})

    filename = file.filename or "demo.dem"
    low_name = filename.lower()
    if not (low_name.endswith(".dem") or low_name.endswith(".zst") or low_name.endswith(".gz")):
        return JSONResponse(status_code=400, content={"success": False, "error": "Nieobsługiwany format pliku. Wymagany plik .dem, .dem.zst lub .dem.gz."})

    faceit_api_key = os.getenv("FACEIT_API_KEY")
    try:
        content = await file.read()
        if len(content) == 0:
            return JSONResponse(status_code=400, content={"success": False, "error": "Przesłany plik jest pusty."})

        result = await analyze_uploaded_demo(db, match_id, faceit_api_key, content, filename)
        if result.get("success"):
            return JSONResponse(content=result)
        else:
            return JSONResponse(status_code=400, content=result)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": f"Błąd podczas przetwarzania pliku: {str(e)}"})
