"""
Plant / campaign / anomaly / WMS router.

Endpoints
---------
GET  /stats
GET  /campagne                           list campaigns
POST /campagne                           create campaign
GET  /campagne/{id}                      get campaign
PATCH /campagne/{id}                     update campaign (WMS URL, stato…)
GET  /campagne/{id}/anomalie             anomalies in campaign
POST /campagne/{id}/import/{scan_id}     import YOLO scan into campaign

GET  /anomalie                           list anomalies (filters: campagna, its, stato, gravita)
GET  /anomalie/{id}                      get anomaly + interventions
PATCH /anomalie/{id}                     update stato / note / component refs
POST /anomalie/{id}/intervento           add maintenance intervention

GET    /wms-layers                       list WMS layers
POST   /wms-layers                       add WMS layer
PATCH  /wms-layers/{id}                  update
DELETE /wms-layers/{id}                  remove
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import (
    AnomaliaTermografica, CampagnaTermografica,
    InterventoManutenzione, WmsLayer, get_db,
)
from app import state

router = APIRouter()

# ── Pydantic schemas ─────────────────────────────────────────────────────────

class CampagnaCreate(BaseModel):
    data_rilievo:  Optional[str]   = None
    operatore:     Optional[str]   = None
    strumento:     Optional[str]   = None
    meteo:         Optional[str]   = None
    irraggiamento: Optional[float] = None
    temperatura:   Optional[float] = None
    url_wms:       Optional[str]   = None
    nome_layer:    Optional[str]   = None
    url_report:    Optional[str]   = None
    stato:         Optional[str]   = "aperta"
    note:          Optional[str]   = None


class AnomaliaUpdate(BaseModel):
    id_its:       Optional[str]   = None
    id_stringa:   Optional[str]   = None
    id_modulo:    Optional[str]   = None
    gravita:      Optional[str]   = None
    delta_t:      Optional[float] = None
    stato:        Optional[str]   = None
    note:         Optional[str]   = None


class InterventoCreate(BaseModel):
    data_intervento: Optional[str] = None
    tipo:            Optional[str] = None
    descrizione:     Optional[str] = None
    esito:           Optional[str] = None
    operatore:       Optional[str] = None
    stato_post:      Optional[str] = None
    documento:       Optional[str] = None


class WmsLayerCreate(BaseModel):
    nome:        Optional[str]   = None
    url:         str
    layer_name:  str
    tipo:        Optional[str]   = "WMS"
    id_campagna: Optional[str]   = None
    opacita:     Optional[float] = 0.75
    attivo:      Optional[bool]  = True


class WmsLayerUpdate(BaseModel):
    nome:       Optional[str]   = None
    opacita:    Optional[float] = None
    attivo:     Optional[bool]  = None
    id_campagna: Optional[str]  = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _new_camp_id(db: Session) -> str:
    year = datetime.utcnow().year
    prefix = f"CAMP-{year}-"
    existing = db.query(CampagnaTermografica).filter(
        CampagnaTermografica.id.like(f"{prefix}%")
    ).count()
    return f"{prefix}{existing + 1:03d}"


def _gravity_from_class(class_name: str) -> str:
    return {
        "hotspot":      "alta",
        "bypass_diode": "media",
        "hot_region":   "media",
        "cold_region":  "bassa",
    }.get(class_name, "media")


def _row(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
def plant_stats(db: Session = Depends(get_db)):
    n_camp  = db.query(CampagnaTermografica).count()
    n_ano   = db.query(AnomaliaTermografica).count()
    n_open  = db.query(AnomaliaTermografica).filter(AnomaliaTermografica.stato == "aperta").count()
    n_int   = db.query(InterventoManutenzione).count()
    by_type = {}
    for a in db.query(AnomaliaTermografica).all():
        by_type[a.tipo_anomalia] = by_type.get(a.tipo_anomalia, 0) + 1
    return {
        "campagne": n_camp,
        "anomalie_totali": n_ano,
        "anomalie_aperte": n_open,
        "interventi": n_int,
        "per_tipo": by_type,
    }


# ── Campagne ─────────────────────────────────────────────────────────────────

@router.get("/campagne")
def list_campagne(db: Session = Depends(get_db)):
    rows = db.query(CampagnaTermografica).order_by(CampagnaTermografica.created_at.desc()).all()
    return [_row(r) for r in rows]


@router.post("/campagne", status_code=201)
def create_campagna(body: CampagnaCreate, db: Session = Depends(get_db)):
    camp = CampagnaTermografica(id=_new_camp_id(db), **body.model_dump(exclude_none=True))
    db.add(camp)
    db.commit()
    db.refresh(camp)
    return _row(camp)


@router.get("/campagne/{camp_id}")
def get_campagna(camp_id: str, db: Session = Depends(get_db)):
    c = db.query(CampagnaTermografica).get(camp_id)
    if not c:
        raise HTTPException(404, f"Campaign '{camp_id}' not found")
    return _row(c)


@router.patch("/campagne/{camp_id}")
def update_campagna(camp_id: str, body: CampagnaCreate, db: Session = Depends(get_db)):
    c = db.query(CampagnaTermografica).get(camp_id)
    if not c:
        raise HTTPException(404, f"Campaign '{camp_id}' not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return _row(c)


@router.get("/campagne/{camp_id}/anomalie")
def campagna_anomalie(camp_id: str, db: Session = Depends(get_db)):
    rows = db.query(AnomaliaTermografica).filter(
        AnomaliaTermografica.id_campagna == camp_id
    ).all()
    out = []
    for r in rows:
        d = _row(r)
        d["interventi"] = [_row(i) for i in r.interventi]
        out.append(d)
    return out


@router.post("/campagne/{camp_id}/import/{scan_id}")
def import_scan(camp_id: str, scan_id: str, db: Session = Depends(get_db)):
    """Import YOLO detection results from in-memory scan into a campaign."""
    c = db.query(CampagnaTermografica).get(camp_id)
    if not c:
        raise HTTPException(404, f"Campaign '{camp_id}' not found")
    scan = state.scan_store.get(scan_id)
    if not scan:
        raise HTTPException(404, f"Scan '{scan_id}' not in memory. Re-run or load first.")

    imported = 0
    for d in scan.defects:
        ano_id = f"ANO-{uuid.uuid4().hex[:8].upper()}"
        its_id = None
        if d.layout_mapping and d.layout_mapping.matched_panel_id not in (None, "UNMATCHED"):
            its_id = d.layout_mapping.matched_panel_id

        ano = AnomaliaTermografica(
            id            = ano_id,
            id_campagna   = camp_id,
            id_its        = its_id,
            tipo_anomalia = d.class_name,
            gravita       = _gravity_from_class(d.class_name),
            confidenza    = d.confidence,
            frames        = d.frames_tracked,
            lat           = d.estimated_coordinates.latitude,
            lon           = d.estimated_coordinates.longitude,
            altezza_m     = d.estimated_coordinates.quadcopter_height_m,
            bbox_avg      = json.dumps(d.bbox_avg) if d.bbox_avg else None,
            foto_termica  = (d.source_images or [None])[0],
            scan_id       = scan_id,
            defect_id     = d.defect_id,
        )
        db.add(ano)
        imported += 1

    db.commit()
    return {"imported": imported, "campaign": camp_id}


# ── Anomalie ─────────────────────────────────────────────────────────────────

@router.get("/anomalie")
def list_anomalie(
    campagna: Optional[str] = None,
    its:      Optional[str] = None,
    stato:    Optional[str] = None,
    gravita:  Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(AnomaliaTermografica)
    if campagna: q = q.filter(AnomaliaTermografica.id_campagna == campagna)
    if its:      q = q.filter(AnomaliaTermografica.id_its == its)
    if stato:    q = q.filter(AnomaliaTermografica.stato == stato)
    if gravita:  q = q.filter(AnomaliaTermografica.gravita == gravita)
    return [_row(r) for r in q.order_by(AnomaliaTermografica.created_at.desc()).all()]


@router.get("/anomalie/{ano_id}")
def get_anomalia(ano_id: str, db: Session = Depends(get_db)):
    a = db.query(AnomaliaTermografica).get(ano_id)
    if not a:
        raise HTTPException(404, f"Anomaly '{ano_id}' not found")
    d = _row(a)
    d["interventi"] = [_row(i) for i in a.interventi]
    return d


@router.patch("/anomalie/{ano_id}")
def update_anomalia(ano_id: str, body: AnomaliaUpdate, db: Session = Depends(get_db)):
    a = db.query(AnomaliaTermografica).get(ano_id)
    if not a:
        raise HTTPException(404, f"Anomaly '{ano_id}' not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(a, k, v)
    db.commit()
    db.refresh(a)
    return _row(a)


@router.post("/anomalie/{ano_id}/intervento", status_code=201)
def add_intervento(ano_id: str, body: InterventoCreate, db: Session = Depends(get_db)):
    a = db.query(AnomaliaTermografica).get(ano_id)
    if not a:
        raise HTTPException(404, f"Anomaly '{ano_id}' not found")
    iv = InterventoManutenzione(id_anomalia=ano_id, **body.model_dump(exclude_none=True))
    db.add(iv)
    if body.esito == "risolto":
        a.stato = "risolta"
    db.commit()
    db.refresh(iv)
    return _row(iv)


# ── WMS Layers ───────────────────────────────────────────────────────────────

@router.get("/wms-layers")
def list_wms(db: Session = Depends(get_db)):
    return [_row(r) for r in db.query(WmsLayer).order_by(WmsLayer.created_at).all()]


@router.post("/wms-layers", status_code=201)
def add_wms(body: WmsLayerCreate, db: Session = Depends(get_db)):
    lyr = WmsLayer(**body.model_dump(exclude_none=True))
    db.add(lyr)
    db.commit()
    db.refresh(lyr)
    return _row(lyr)


@router.patch("/wms-layers/{lyr_id}")
def update_wms(lyr_id: int, body: WmsLayerUpdate, db: Session = Depends(get_db)):
    lyr = db.query(WmsLayer).get(lyr_id)
    if not lyr:
        raise HTTPException(404, "WMS layer not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(lyr, k, v)
    db.commit()
    db.refresh(lyr)
    return _row(lyr)


@router.delete("/wms-layers/{lyr_id}", status_code=204)
def delete_wms(lyr_id: int, db: Session = Depends(get_db)):
    lyr = db.query(WmsLayer).get(lyr_id)
    if lyr:
        db.delete(lyr)
        db.commit()
