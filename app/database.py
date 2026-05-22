"""
SQLite persistence layer (SQLAlchemy).

Tables
------
campagne_termografiche   — thermal inspection campaigns
anomalie_termografiche   — georeferenced anomalies linked to ITS / string / module
interventi_manutentivi   — maintenance interventions per anomaly
wms_layers               — configured WMS/WMTS layers
"""
from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "autothermo.db")
_DB_URL  = f"sqlite:///{os.path.abspath(_DB_PATH)}"

engine       = create_engine(_DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)


# ── Models ───────────────────────────────────────────────────────────────────

class CampagnaTermografica(Base):
    __tablename__ = "campagne_termografiche"

    id            = Column(String,  primary_key=True)   # CAMP-2026-001
    id_impianto   = Column(String,  default="24S002_2E400")
    data_rilievo  = Column(String)                       # ISO date YYYY-MM-DD
    operatore     = Column(String)
    strumento     = Column(String)
    meteo         = Column(String)
    irraggiamento = Column(Float)                        # W/m²
    temperatura   = Column(Float)                        # °C ambientale
    url_wms       = Column(String)
    nome_layer    = Column(String)
    url_report    = Column(String)
    stato         = Column(String, default="aperta")     # aperta | validata | chiusa
    note          = Column(Text)
    created_at    = Column(DateTime, default=datetime.utcnow)

    anomalie   = relationship("AnomaliaTermografica", back_populates="campagna",
                              cascade="all, delete-orphan")
    wms_layers = relationship("WmsLayer", back_populates="campagna")


class AnomaliaTermografica(Base):
    __tablename__ = "anomalie_termografiche"

    id            = Column(String,  primary_key=True)     # DEF-XXXX or ANO-XXXX
    id_campagna   = Column(String,  ForeignKey("campagne_termografiche.id"))
    id_impianto   = Column(String,  default="24S002_2E400")
    id_its        = Column(String)                         # ITS12
    id_stringa    = Column(String)
    id_modulo     = Column(String)
    tipo_anomalia = Column(String)                         # hotspot | bypass_diode | hot_region | cold_region
    gravita       = Column(String,  default="media")       # bassa | media | alta | critica
    delta_t       = Column(Float)                          # ΔT °C (if known)
    confidenza    = Column(Float)
    frames        = Column(Integer)
    lat           = Column(Float)
    lon           = Column(Float)
    altezza_m     = Column(Float)
    bbox_avg      = Column(String)                         # JSON "[x1,y1,x2,y2]"
    foto_termica  = Column(String)                         # path to best source image
    note          = Column(Text)
    stato         = Column(String, default="aperta")       # aperta | assegnata | risolta | chiusa
    scan_id       = Column(String)
    defect_id     = Column(String)                         # DEF-XXXX from YOLO
    created_at    = Column(DateTime, default=datetime.utcnow)

    campagna    = relationship("CampagnaTermografica", back_populates="anomalie")
    interventi  = relationship("InterventoManutenzione", back_populates="anomalia",
                               cascade="all, delete-orphan")


class InterventoManutenzione(Base):
    __tablename__ = "interventi_manutentivi"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    id_anomalia     = Column(String,  ForeignKey("anomalie_termografiche.id"))
    data_intervento = Column(String)
    tipo            = Column(String)                       # sostituzione | pulizia | verifica | altro
    descrizione     = Column(Text)
    esito           = Column(String)                       # risolto | parziale | non_risolto
    operatore       = Column(String)
    stato_post      = Column(String)
    documento       = Column(String)
    created_at      = Column(DateTime, default=datetime.utcnow)

    anomalia = relationship("AnomaliaTermografica", back_populates="interventi")


class WmsLayer(Base):
    __tablename__ = "wms_layers"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    nome        = Column(String)
    url         = Column(String)
    layer_name  = Column(String)
    tipo        = Column(String,  default="WMS")           # WMS | WMTS
    id_campagna = Column(String,  ForeignKey("campagne_termografiche.id"), nullable=True)
    opacita     = Column(Float,   default=0.75)
    attivo      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    campagna = relationship("CampagnaTermografica", back_populates="wms_layers")
