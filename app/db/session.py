import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

import urllib.parse

# Pobieramy URL bazy ze zmiennych środowiskowych. 
# Na Render będzie to zewnętrzna baza, lokalnie - SQLite.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./clutchdata.db").strip().strip("'\"")

# Render/Neon nadaje URL zaczynający się od "postgres://" lub "postgresql://", 
# ale SQLAlchemy wymaga wariantu asyncpg, czyli "postgresql+asyncpg://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Oczyszczanie parametrów zapytania (np. sslmode, channel_binding), które dodaje Neon,
# ale których asyncpg nie przyjmuje jako keyword arguments
if "asyncpg" in DATABASE_URL and "?" in DATABASE_URL:
    base_url_part, query_part = DATABASE_URL.split("?", 1)
    query_params = urllib.parse.parse_qs(query_part)
    unsupported_asyncpg_args = {"sslmode", "channel_binding", "target_session_attrs"}
    filtered_params = {k: v[0] for k, v in query_params.items() if k not in unsupported_asyncpg_args}
    if filtered_params:
        DATABASE_URL = f"{base_url_part}?{urllib.parse.urlencode(filtered_params)}"
    else:
        DATABASE_URL = base_url_part

engine_kwargs = {}
if "sqlite" in DATABASE_URL:
    engine_kwargs["connect_args"] = {"timeout": 30}
else:
    # Zabezpieczenie przed zrywaniem połączeń w serverless Postgres (Neon) oraz wymagane SSL
    engine_kwargs["connect_args"] = {"ssl": True}
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300

# Tworzymy "silnik" łączący się z bazą
engine = create_async_engine(DATABASE_URL, echo=False, **engine_kwargs)

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
