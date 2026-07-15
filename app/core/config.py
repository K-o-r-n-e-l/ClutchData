from pydantic import BaseSettings


class Settings(BaseSettings):
    app_name: str = "ClutchDATA"
    debug: bool = True
    version: str = "0.1.0"

    class Config:
        env_file = ".env"


settings = Settings()
