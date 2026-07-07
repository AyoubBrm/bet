from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from ..database import Base

class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"))
    name = Column(String, nullable=False)

    event = relationship("Event", back_populates="players")
    odds = relationship("PlayerShotOdds", back_populates="player", cascade="all, delete")
    tackle_odds = relationship("PlayerTackleOdds", back_populates="player", cascade="all, delete")
