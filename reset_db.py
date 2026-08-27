import os
import asyncio
from dotenv import load_dotenv
from sqlalchemy import delete

load_dotenv()

from app.db.session import SessionLocal, engine, Base, DATABASE_URL
import app.db.models


async def create_fresh_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


def reset_sqlite_file():
    db_filename = "clutchdata.db"
    for ext in ["", "-journal", "-wal", "-shm"]:
        fpath = db_filename + ext
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except PermissionError:
                print("\n[BLAD BLOKADY SQLITE] Plik 'clutchdata.db' jest zablokowany przez dzialajacy serwer uvicorn.")
                print("Instrukcja:")
                print("  1. Wcisnij Ctrl+C w terminalu, w ktorym masz wlaczony serwer 'uvicorn'.")
                print("  2. Uruchom 'python reset_db.py' ponownie.")
                print("  3. Wlacz uvicorn na nowo: uvicorn app.main:app --reload\n")
                return False
    return True


async def clear_postgres_tables():
    async with SessionLocal() as db:
        await db.execute(delete(app.db.models.PlayerRoundStatistic))
        await db.execute(delete(app.db.models.MatchStatistic))
        await db.execute(delete(app.db.models.MatchRound))
        await db.execute(delete(app.db.models.Match))
        await db.execute(delete(app.db.models.EloHistory))
        await db.execute(delete(app.db.models.Player))
        await db.commit()
    await engine.dispose()


async def main():
    print("[RESET] Rozpoczynam czyszczenie bazy danych...")
    if "sqlite" in DATABASE_URL:
        if reset_sqlite_file():
            await create_fresh_tables()
            print("[SUKCES] Baza SQLite zostala wyczyszczona i przygotowana do testow (0 wierszy).")
    else:
        await clear_postgres_tables()
        print("[SUKCES] Tabele w bazie PostgreSQL zostaly wyczyszczone (0 wierszy).")


if __name__ == "__main__":
    asyncio.run(main())
