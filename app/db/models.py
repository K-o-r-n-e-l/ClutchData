from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Boolean
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
    
    # Flaga dla subskrybentów ClutchData+ (śledzenie meczów przez webhooki)
    clutchdata_plus = Column(Boolean, default=False)
    
    # Relacje
    elo_history = relationship("EloHistory", back_populates="player", cascade="all, delete-orphan")
    match_stats = relationship("MatchStatistic", back_populates="player", cascade="all, delete-orphan")

class EloHistory(Base):
    __tablename__ = "elo_history"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    
    # Zapisane ELO z Faceit
    faceit_elo = Column(Integer, nullable=False)
    
    # Kiedy został zapisany ten wynik
    recorded_at = Column(DateTime, default=datetime.utcnow)
    
    player = relationship("Player", back_populates="elo_history")

class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    # Zewnętrzne ID z Faceit np. '1-3316f7c8-3c3e-4361-9c70-20539f99e691'
    faceit_match_id = Column(String, unique=True, index=True, nullable=False)
    map_name = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    
    stats = relationship("MatchStatistic", back_populates="match", cascade="all, delete-orphan")
    rounds = relationship("MatchRound", back_populates="match", cascade="all, delete-orphan")

class MatchStatistic(Base):
    __tablename__ = "match_statistics"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    
    # ELO nagrane w trakcie tego meczu
    elo_history_id = Column(Integer, ForeignKey("elo_history.id"), nullable=True)

    # Obliczony z algorytmu dla dema
    clutchdata_rating = Column(Float, default=0.0)
    
    # Statystyki z dema: entry
    entry_attempts = Column(Integer, default=0)
    entry_success = Column(Integer, default=0)
    
    # Próby 1vsX
    clutch_1v1_attempts = Column(Integer, default=0)
    clutch_1v2_attempts = Column(Integer, default=0)
    clutch_1v3_attempts = Column(Integer, default=0)
    clutch_1v4_attempts = Column(Integer, default=0)
    clutch_1v5_attempts = Column(Integer, default=0)
    
    
    clutch_1v1_wins = Column(Integer, default=0)
    clutch_1v2_wins = Column(Integer, default=0)
    clutch_1v3_wins = Column(Integer, default=0)
    clutch_1v4_wins = Column(Integer, default=0)
    clutch_1v5_wins = Column(Integer, default=0)

    # Dodatkowe propozycje od Antigravity
    trade_kills = Column(Integer, default=0)  # Zabójstwa wymieniające kompana z drużyny
    utility_damage = Column(Integer, default=0)  # Obrażenia zadane przez utility (HE, molly)
    enemies_flashed = Column(Integer, default=0)  # Realna liczba oślepionych przeciwników
    flash_assists = Column(Integer, default=0)  # Liczba zabójstw przeciwników, którzy zostali oślepieni przez gracza

    # Relacje zwrotne
    match = relationship("Match", back_populates="stats")
    player = relationship("Player", back_populates="match_stats")
    elo_history = relationship("EloHistory")

class MatchRound(Base):
    __tablename__ = "match_rounds"
    
    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    round_number = Column(Integer, nullable=False)
    
    winning_side = Column(String, nullable=True) # np. CT, T
    win_reason = Column(String, nullable=True) # np. BombDefused, TargetBombed, itp.
    duration_seconds = Column(Float, nullable=True)
    
    match = relationship("Match", back_populates="rounds")
    player_stats = relationship("PlayerRoundStatistic", back_populates="round", cascade="all, delete-orphan")

class PlayerRoundStatistic(Base):
    __tablename__ = "player_round_statistics"
    
    id = Column(Integer, primary_key=True, index=True)
    match_round_id = Column(Integer, ForeignKey("match_rounds.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    
    side_played = Column(String, nullable=False) # CT lub T dla tego gracza w tej rundzie
    
    # Rating z danej rundy (wpływ na ClutchRating)
    clutchdata_rating_impact = Column(Float, default=0.0)
    
    # K/D/A w samej rundzie
    kills = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    deaths = Column(Integer, default=0)
    damage_dealt = Column(Float, default=0.0)
    
    # Elementy ratingu (entry, flash, trade)
    utility_damage = Column(Float, default=0.0)
    enemies_flashed = Column(Integer, default=0)
    trade_kills = Column(Integer, default=0)
    
    was_entry_attempt = Column(Boolean, default=False)
    was_entry_success = Column(Boolean, default=False)
    
    # Sytuacje clutch (zapisujemy scenariusz, np "1v2" i to czy go wygrał w tej rundzie)
    clutch_scenario = Column(String, nullable=True) # Zostawiamy puste, jeśli nie został sam
    clutch_won = Column(Boolean, default=False)
    
    round = relationship("MatchRound", back_populates="player_stats")
    player = relationship("Player")
