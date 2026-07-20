import os
from dotenv import load_dotenv

# Load environment variables early
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from app.api.routes import router as api_router
from app.web.routes import router as web_router
from contextlib import asynccontextmanager
from app.db.session import engine, Base
import app.db.models  # Ważne: importujemy modele, aby SQLAlchemy o nich wiedziało

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tworzymy tabele w bazie danych podczas startu aplikacji (tylko do celów deweloperskich/testowych)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(title="ClutchDATA", version="0.1.0", lifespan=lifespan)

# Add session middleware for storing Steam login session
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "fallback_secret"))

# Mount static files
import pathlib
static_path = pathlib.Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(web_router)
app.include_router(api_router)

@app.get("/health")
def health_check():
    return {"status": "ok", "app": "ClutchDATA"}
