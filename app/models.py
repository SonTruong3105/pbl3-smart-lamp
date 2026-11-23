from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from app.database import Base


class Device(Base):
    __tablename__ = "devices"
    id = Column(String, primary_key=True)
    name = Column(String, default="Unknown")
    type = Column(String, default="browser")
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_devices_last_seen", "last_seen"),)


class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String, ForeignKey("devices.id"), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    last_activity_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    message_count = Column(Integer, default=0)
    __table_args__ = (
        Index("ix_sessions_device_id_id", "device_id", "id"),
        Index("ix_sessions_last_activity_at", "last_activity_at"),
    )


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"))
    role = Column(String)
    content = Column(Text)
    audio_path = Column(String, nullable=True)
    turn_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_messages_session_id_id", "session_id", "id"),)


# Calendar models
class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id = Column(String, primary_key=True)
    device_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=False)
    date = Column(String, nullable=False, index=True)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    note = Column(Text, default="")
    remind_minutes = Column(Integer, default=0)
    revision = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class CalendarReminder(Base):
    __tablename__ = "calendar_reminders"
    id = Column(String, primary_key=True)
    event_id = Column(String, ForeignKey("calendar_events.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    payload = Column(Text, nullable=False)
    status = Column(String, default="pending")
    active = Column(Integer, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow)