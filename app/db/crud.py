from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.models import Player, EloHistory

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

async def get_player_by_steam_id(db: AsyncSession, steam_id: str):
    result = await db.execute(select(Player).filter(Player.steam_id == steam_id))
    return result.scalars().first()

async def enable_clutchdata_plus(db: AsyncSession, steam_id: str):
    player = await get_player_by_steam_id(db, steam_id)
    if player:
        player.clutchdata_plus = True
        await db.commit()
        return True
    return False
