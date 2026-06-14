from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SubmissionStatus(str, enum.Enum):
    pending_match = "pending_match"
    drafted = "drafted"
    approved = "approved"
    rejected = "rejected"


class DraftStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Film(Base):
    __tablename__ = "films"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    imdb_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    original_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    release_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imdb_rating: Mapped[str | None] = mapped_column(String(16), nullable=True)
    genres: Mapped[list[str]] = mapped_column(JSON, default=list)
    similar_movies: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    drafts: Mapped[list[Draft]] = relationship(back_populates="film")


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_file_id: Mapped[str] = mapped_column(String(255))
    submitted_title: Mapped[str] = mapped_column(String(255))
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus), default=SubmissionStatus.pending_match
    )
    admin_user_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    drafts: Mapped[list[Draft]] = relationship(back_populates="submission")


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"))
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id"))
    status: Mapped[DraftStatus] = mapped_column(Enum(DraftStatus), default=DraftStatus.pending)
    
    video_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_text: Mapped[str] = mapped_column(Text)
    fact_text: Mapped[str] = mapped_column(Text)
    recommendations_text: Mapped[str] = mapped_column(Text)
    
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    film: Mapped[Film] = relationship(back_populates="drafts")
    submission: Mapped[Submission] = relationship(back_populates="drafts")
    published_post: Mapped[PublishedPost | None] = relationship(back_populates="draft")
    campaign: Mapped[Campaign | None] = relationship(back_populates="draft")


class PublishedPost(Base):
    __tablename__ = "published_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), unique=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id"))
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    local_date: Mapped[date] = mapped_column(Date, index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    draft: Mapped[Draft] = relationship(back_populates="published_post")
    film: Mapped[Film] = relationship()


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), unique=True)
    local_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    
    teaser_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    review_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fact_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    recommendation_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    poll_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    poll_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    draft: Mapped[Draft] = relationship(back_populates="campaign")


class NewsPost(Base):
    __tablename__ = "news_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
