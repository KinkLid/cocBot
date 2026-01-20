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
    token_hash: Mapped[Optional[str]] = mapped_column(String(64))
    last_clan_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_in_clan_cached: Mapped[Optional[bool]] = mapped_column(Boolean)
    first_seen_in_clan_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_seen_in_main_chat: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    main_chat_member_check_ok: Mapped[Optional[bool]] = mapped_column(Boolean)
    role_flags: Mapped[int] = mapped_column(Integer, default=0)
    notify_pref: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_stats_message_id: Mapped[Optional[int]] = mapped_column(Integer)
    seen_hint_targets: Mapped[Optional[bool]] = mapped_column(Boolean)
    seen_hint_notify: Mapped[Optional[bool]] = mapped_column(Boolean)
    seen_hint_stats: Mapped[Optional[bool]] = mapped_column(Boolean)
    seen_hint_admin_notify: Mapped[Optional[bool]] = mapped_column(Boolean)
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


class CwlWarState(Base):
    __tablename__ = "cwl_war_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[str] = mapped_column(String(16))
    war_tag: Mapped[str] = mapped_column(String(32), unique=True)
    state: Mapped[str] = mapped_column(String(16))
    last_notified_state: Mapped[Optional[str]] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class CapitalRaidState(Base):
    __tablename__ = "capital_raid_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raid_id: Mapped[str] = mapped_column(String(64), unique=True)
    state: Mapped[str] = mapped_column(String(16))
    last_notified_state: Mapped[Optional[str]] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ScheduledNotification(Base):
    __tablename__ = "scheduled_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[str] = mapped_column(String(32))
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message_text: Mapped[str] = mapped_column(Text)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16))
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    event_type: Mapped[str] = mapped_column(String(16))
    delay_seconds: Mapped[int] = mapped_column(Integer)
    custom_text: Mapped[Optional[str]] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class NotificationInstance(Base):
    __tablename__ = "notification_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("notification_rules.id"))
    event_id: Mapped[str] = mapped_column(String(64))
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_by_tg_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_by_tg_name: Mapped[Optional[str]] = mapped_column(String(128))
    target_player_tag: Mapped[str] = mapped_column(String(16))
    target_player_name: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="open")


class WarAttackEvent(Base):
    __tablename__ = "war_attack_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    war_tag: Mapped[str] = mapped_column(String(32))
    attacker_tag: Mapped[str] = mapped_column(String(16))
    defender_tag: Mapped[str] = mapped_column(String(16))
    attack_order: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "war_tag",
            "attacker_tag",
            "defender_tag",
            "attack_order",
            name="uq_war_attack_event",
        ),
        Index("idx_war_attack_event_war", "war_tag"),
    )


class ClanMemberState(Base):
    __tablename__ = "clan_member_state"

    player_tag: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_seen_name: Mapped[str] = mapped_column(String(64))
    last_seen_in_clan_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_rejoined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    leave_count: Mapped[int] = mapped_column(Integer, default=0)
    is_in_clan: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class BlacklistPlayer(Base):
    __tablename__ = "blacklist_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_tag: Mapped[str] = mapped_column(String(16), unique=True)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    added_by_admin_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WhitelistPlayer(Base):
    __tablename__ = "whitelist_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_tag: Mapped[str] = mapped_column(String(16), unique=True)
    player_name: Mapped[Optional[str]] = mapped_column(String(64))
    comment: Mapped[Optional[str]] = mapped_column(Text)
    added_by_admin_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
