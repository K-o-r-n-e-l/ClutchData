from fastapi import APIRouter, Request
from app.schemas.player import PlayerStatsResponse
from app.services.stats import get_player_stats

router = APIRouter(prefix="/api")


@router.post("/webhooks/faceit")
async def faceit_webhook(request: Request):
    # Krok 1: Odbieramy "paczkę" od Faceit
    payload = await request.json()
    
    # Krok 2: Sprawdzamy co to za zdarzenie (interesuje nas tylko koniec meczu)
    event_name = payload.get("event")
    
    if event_name == "match_status_finished":
        print("🎉 Faceit przysłał webhook o zakończonym meczu!")
        match_id = payload.get("payload", {}).get("id")
        print(f"ID Meczu: {match_id}")
        
        # W przyszłości: Tutaj wywołamy logikę, która zaktualizuje ELO w naszej bazie
        
    return {"status": "ok", "message": "Webhook odebrany!"}
