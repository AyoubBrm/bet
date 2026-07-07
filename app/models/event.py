from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from ..database import Base

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True)
    home = Column(String, nullable=False)
    away = Column(String, nullable=False)
    date = Column(DateTime, nullable=False)

    players = relationship("Player", back_populates="event", cascade="all, delete")
