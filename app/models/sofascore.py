from sqlalchemy import Column, Integer, String, DateTime, JSON
from datetime import datetime, timezone
from app.database import Base

class SofascoreCache(Base):
    __tablename__ = "sofascore_cache"
    
    date = Column(String, primary_key=True, index=True)
    data = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PlayerHistory(Base):
    __tablename__ = "player_history"
    
    player_id = Column(String, primary_key=True, index=True)
    history = Column(JSON, nullable=False, default=list)
    last_synced = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SyncedMatch(Base):
    __tablename__ = "synced_matches"
    
    match_id = Column(String, primary_key=True, index=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

class SofascoreMatchCache(Base):
    __tablename__ = "sofascore_match_cache"

    match_id = Column(String, primary_key=True, index=True)
    bet365_event_id = Column(String, index=True, nullable=True)
    date = Column(String, index=True, nullable=False)
    home = Column(String, nullable=True)
    away = Column(String, nullable=True)
    start_timestamp = Column(Integer, index=True, nullable=True)
    data = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Bet365SofascoreMapping(Base):
    __tablename__ = "bet365_sofascore_mapping"

    bet365_event_id = Column(String, primary_key=True, index=True)
    sofascore_event_id = Column(String, index=True, nullable=False)
    date = Column(String, index=True, nullable=False)
    home = Column(String, nullable=True)
    away = Column(String, nullable=True)
    start_timestamp = Column(Integer, index=True, nullable=True)
    sync_status = Column(String, default="pending", index=True)
    event_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
