from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.database import Base


class Device(Base):
    __tablename__ = "devices"
    id = Column(String, primary_key=True)
    name = Column(String, default="Unknown")
    type = Column(String, default="browser")
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)


class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String, ForeignKey("devices.id"), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    message_count = Column(Integer, default=0)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"))
    role = Column(String)
    content = Column(Text)
    audio_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)