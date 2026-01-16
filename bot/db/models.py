from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    player_tag: Mapped[str] = mapped_column(String(16), unique=True)
    player_name: Mapped[str] = mapped_column(String(64))
    clan_tag: Mapped[str] = mapped_column(String(16))
    role_flags: Mapped[int] = mapped_column(Integer, default=0)
    notify_pref: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_stats_message_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    war_participations: Mapped[list[WarParticipation]] = relationship(
        "WarParticipation", back_populates="user", cascade="all, delete-orphan"
    )
    capital_contribs: Mapped[list[CapitalContribution]] = relationship(
        "CapitalContribution", back_populates="user", cascade="all, delete-orphan"
    )
    target_claims: Mapped[list[TargetClaim]] = relationship(
        "TargetClaim", back_populates="user", cascade="all, delete-orphan"
    )


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class StatsDaily(Base):
    __tablename__ = "stats_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class War(Base):
    __tablename__ = "wars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    war_tag: Mapped[Optional[str]] = mapped_column(String(32), unique=True)
    war_type: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))
    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    opponent_name: Mapped[Optional[str]] = mapped_column(String(64))
    opponent_tag: Mapped[Optional[str]] = mapped_column(String(16))
    league_name: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    participations: Mapped[list[WarParticipation]] = relationship(
        "WarParticipation", back_populates="war", cascade="all, delete-orphan"
    )


class WarParticipation(Base):
    __tablename__ = "war_participation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    war_id: Mapped[int] = mapped_column(Integer, ForeignKey("wars.id"))
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    attacks_used: Mapped[int] = mapped_column(Integer, default=0)
    attacks_available: Mapped[int] = mapped_column(Integer, default=0)
    stars: Mapped[int] = mapped_column(Integer, default=0)
    destruction: Mapped[int] = mapped_column(Integer, default=0)
    missed_attacks: Mapped[int] = mapped_column(Integer, default=0)

    war: Mapped[War] = relationship("War", back_populates="participations")
    user: Mapped[User] = relationship("User", back_populates="war_participations")


class CapitalRaidSeason(Base):
    __tablename__ = "capital_raid_seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raid_id: Mapped[str] = mapped_column(String(32), unique=True)
    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    total_loot: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    contributions: Mapped[list[CapitalContribution]] = relationship(
        "CapitalContribution", back_populates="season", cascade="all, delete-orphan"
    )


class CapitalContribution(Base):
    __tablename__ = "capital_contrib"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(Integer, ForeignKey("capital_raid_seasons.id"))
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    attacks: Mapped[int] = mapped_column(Integer, default=0)
    raids_completed: Mapped[int] = mapped_column(Integer, default=0)
    capital_gold_donated: Mapped[int] = mapped_column(Integer, default=0)
    damage: Mapped[int] = mapped_column(Integer, default=0)

    season: Mapped[CapitalRaidSeason] = relationship("CapitalRaidSeason", back_populates="contributions")
    user: Mapped[User] = relationship("User", back_populates="capital_contribs")


class TargetClaim(Base):
    __tablename__ = "target_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    war_id: Mapped[int] = mapped_column(Integer, ForeignKey("wars.id"))
    enemy_position: Mapped[int] = mapped_column(Integer)
    claimed_by_telegram_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id")
    )
    external_player_name: Mapped[Optional[str]] = mapped_column(String(64))
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    user: Mapped[User] = relationship("User", back_populates="target_claims")

    __table_args__ = (
        UniqueConstraint("war_id", "enemy_position", name="uq_target_claim"),
        Index("idx_target_claim_war", "war_id"),
    )


class ChatNotificationSetting(Base):
    __tablename__ = "chat_notify_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class WarState(Base):
    __tablename__ = "war_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    war_tag: Mapped[Optional[str]] = mapped_column(String(32), unique=True)
    state: Mapped[str] = mapped_column(String(16))
    last_notified_state: Mapped[Optional[str]] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class WarReminder(Base):
    __tablename__ = "war_reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    war_id: Mapped[int] = mapped_column(Integer, ForeignKey("wars.id"))
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message_text: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(16), default="pending")


class CwlState(Base):
    __tablename__ = "cwl_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[str] = mapped_column(String(16), unique=True)
    state: Mapped[str] = mapped_column(String(16))
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
