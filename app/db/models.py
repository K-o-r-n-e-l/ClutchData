from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from .session import Base

class Player(Base):
    __tablename__ = "players"

    # ID z bazy danych (unikalne)
    id = Column(Integer, primary_key=True, index=True)
    
    # 17-cyfrowe SteamID
    steam_id = Column(String, unique=True, index=True, nullable=False)
    
    # Podstawowe info, by łatwiej szukać po bazie
    persona_name = Column(String, nullable=True)
    
    # Relacja do historii ELO
    elo_history = relationship("EloHistory", back_populates="player")

class EloHistory(Base):
    __tablename__ = "elo_history"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    
    # Zapisane ELO z Faceit
    faceit_elo = Column(Integer, nullable=False)
    
    # Kiedy został zapisany ten wynik
    recorded_at = Column(DateTime, default=datetime.utcnow)
    
    player = relationship("Player", back_populates="elo_history")
