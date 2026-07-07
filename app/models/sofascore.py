from sqlalchemy import Column, String, DateTime, JSON
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
