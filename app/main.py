import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from app.api.routes import router as api_router
from app.web.routes import router as web_router

# Load environment variables
load_dotenv()

app = FastAPI(title="ClutchDATA", version="0.1.0")

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
