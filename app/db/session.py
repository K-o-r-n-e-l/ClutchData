import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# Pobieramy URL bazy ze zmiennych środowiskowych. 
# Na Render będzie to zewnętrzna baza, lokalnie - SQLite.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./clutchdata.db").strip().strip("'\"")

# Render nadaje URL zaczynający się od "postgres://" lub "postgresql://", 
# ale SQLAlchemy wymaga wariantu asyncpg, czyli "postgresql+asyncpg://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

connect_args = {"timeout": 30} if "sqlite" in DATABASE_URL else {}
# Tworzymy "silnik" łączący się z bazą
engine = create_async_engine(DATABASE_URL, echo=False, connect_args=connect_args)

# Fabryka sesji - sesja to takie okienko, przez które rozmawiamy z bazą w trakcie jednego zapytania użytkownika na stronie
SessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Baza dla naszych modeli - użyjemy jej w models.py
Base = declarative_base()

# Funkcja pomocnicza dla FastAPI do wstrzykiwania bazy danych do widoków
async def get_db():
    async with SessionLocal() as session:
        yield session
