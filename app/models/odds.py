from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from ..database import Base

class PlayerShotOdds(Base):
    __tablename__ = "player_shot_odds"
    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"))
    shot_line = Column(String, nullable=False)  # e.g. "shot 1+"
    odds_value = Column(Float, nullable=False)

    player = relationship("Player", back_populates="odds")

class PlayerTackleOdds(Base):
    __tablename__ = "player_tackle_odds"
    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"))
    tackle_line = Column(String, nullable=False)  # e.g. "Tackle 1+"
    odds_value = Column(Float, nullable=False)

    player = relationship("Player", back_populates="tackle_odds")
