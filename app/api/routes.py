from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.schemas.player import PlayerStatsResponse
from app.services.stats import get_player_stats
from app.services.faceit_stats import load_faceit_data, fetch_match_stats
import os
import httpx
import asyncio

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/api")
from app.services.demo_worker import process_match_background

@router.post("/webhooks/faceit")
async def faceit_webhook(request: Request, background_tasks: BackgroundTasks):
    # Krok 1: Odbieramy "paczkę" od Faceit
    payload = await request.json()
    
    # Krok 2: Sprawdzamy co to za zdarzenie (interesuje nas tylko koniec meczu)
    event_name = payload.get("event")
    
    if event_name == "match_status_finished":
        match_id = payload.get("payload", {}).get("id")
        print(f"🎉 Faceit przysłał webhook o zakończonym meczu! ID Meczu: {match_id}")
        
        # Odsyłamy proces pobierania dema, analizy i czyszczenia pliku do TŁA!
        # Faceit otrzyma natychmiast status 200 OK
        background_tasks.add_task(process_match_background, match_id)
        
    return {"status": "ok", "message": "Webhook odebrany! Analiza odbywa się w tle."}

@router.get("/player/{steam_id}/history", response_class=HTMLResponse)
async def get_player_history(request: Request, steam_id: str, offset: int = 10):
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
        
    return templates.TemplateResponse(
        request=request,
        name="_match_rows.html",
        context={"faceit_history": faceit_history}
    )
