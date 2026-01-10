"""Database models for GameDB."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    BigInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class System(Base):
    __tablename__ = "systems"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)

    titles = relationship("Title", back_populates="system")


class Title(Base):
    __tablename__ = "titles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    system_id = Column(Integer, ForeignKey("systems.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    system = relationship("System", back_populates="titles")
    releases = relationship("Release", back_populates="title")

    __table_args__ = (
        UniqueConstraint("system_id", "name", name="uq_titles_system_name"),
    )


class Release(Base):
    __tablename__ = "releases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title_id = Column(Integer, ForeignKey("titles.id"), nullable=False)
    region = Column(String, nullable=True)
    release_year = Column(Integer, nullable=True)
    release_month = Column(Integer, nullable=True)
    serial = Column(String, nullable=True)
    display_name = Column(String, nullable=True)

    title = relationship("Title", back_populates="releases")
    roms = relationship("Rom", back_populates="release")

    __table_args__ = (
        Index("idx_releases_title_region", "title_id", "region"),
    )


class Rom(Base):
    __tablename__ = "roms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    release_id = Column(Integer, ForeignKey("releases.id"), nullable=False)
    rom_name = Column(String, nullable=True)
    size = Column(BigInteger, nullable=True)
    crc = Column(String, nullable=True)
    md5 = Column(String, nullable=True)
    sha1 = Column(String, nullable=True)

    release = relationship("Release", back_populates="roms")

    __table_args__ = (
        Index("idx_roms_crc", "crc"),
        Index("idx_roms_md5", "md5"),
        Index("idx_roms_sha1", "sha1"),
    )


class Attribute(Base):
    __tablename__ = "attributes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=False)
    key = Column(String, nullable=False)
    value = Column(Text, nullable=True)
    source = Column(String, nullable=True)

    __table_args__ = (
        Index("idx_attributes_entity", "entity_type", "entity_id", "key"),
    )
