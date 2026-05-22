"""
AutoThermo FastAPI application.

Endpoints
---------
GET  /health
POST /scan              Stage 1 — detect, track, geolocate
POST /upload-layout     Stage 2a — ingest panel layout (GeoJSON or CSV)
POST /map/{scan_id}     Stage 2b — match defects to panel IDs using stored layout
POST /pipeline          Stage 1 + 2 in one call (layout_path optional in body)
GET  /results/{scan_id} retrieve stored scan results
"""
from __future__ import annotations

import os
import uuid
from typing import Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import OUTPUTS_DIR
from app.layout_mapper import LayoutStore
from app.models import (
    DefectRecord,
    FullPipelineRequest,
    LayoutMapping,
    ScanRequest,
    ScanResponse,
)
from app.tracker_pipeline import _find_images, run_pipeline

os.makedirs(OUTPUTS_DIR, exist_ok=True)

app = FastAPI(
    title="AutoThermo",
    description="Automated PV panel anomaly detection, tracking, geolocation and layout mapping.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory state (cleared on restart)
_scan_store: Dict[str, ScanResponse] = {}
_layout_store: Optional[LayoutStore] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_layout(defects: List[DefectRecord], store: LayoutStore) -> List[DefectRecord]:
    mapped: List[DefectRecord] = []
    for d in defects:
        lat = d.estimated_coordinates.latitude
        lon = d.estimated_coordinates.longitude
        panel_id, dist_m = store.match(lat, lon)
        mapped.append(d.model_copy(update={
            "layout_mapping": LayoutMapping(
                matched_panel_id=panel_id,
                distance_to_panel_center_m=dist_m,
            )
        }))
    return mapped


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "layout_loaded": _layout_store is not None and len(_layout_store.panels) > 0}


@app.post("/scan", response_model=ScanResponse)
def scan(req: ScanRequest):
    """Stage 1: YOLO detection + ByteTrack + geolocation."""
    global _scan_store
    try:
        defects = run_pipeline(
            directory=req.path,
            conf=req.conf or 0.25,
            iou=req.iou or 0.45,
            min_frames=req.min_frames or 2,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        n_frames = len(_find_images(req.path))
    except Exception:
        n_frames = 0

    scan_id = str(uuid.uuid4())[:8]
    resp = ScanResponse(
        scan_id=scan_id,
        total_frames=n_frames,
        defects_found=len(defects),
        defects=defects,
    )
    _scan_store[scan_id] = resp
    return resp


@app.post("/upload-layout")
async def upload_layout(file: UploadFile = File(...)):
    """Upload a GeoJSON or CSV panel layout file. Replaces any previously loaded layout."""
    global _layout_store
    content = await file.read()
    filename = file.filename or ""
    store = LayoutStore()
    try:
        if filename.lower().endswith(".csv"):
            n = store.load_csv(content)
        else:
            n = store.load_geojson(content)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse layout: {exc}")
    _layout_store = store
    return {"panels_loaded": n, "filename": filename}


@app.post("/map/{scan_id}", response_model=ScanResponse)
def map_layout(scan_id: str):
    """Apply the currently loaded layout to an existing scan, assigning panel IDs to defects."""
    if scan_id not in _scan_store:
        raise HTTPException(status_code=404, detail=f"Scan '{scan_id}' not found.")
    if _layout_store is None or not _layout_store.panels:
        raise HTTPException(status_code=422, detail="No layout loaded. POST /upload-layout first.")

    updated_scan = _scan_store[scan_id].model_copy(update={
        "defects": _apply_layout(_scan_store[scan_id].defects, _layout_store)
    })
    _scan_store[scan_id] = updated_scan
    return updated_scan


@app.post("/pipeline", response_model=ScanResponse)
def full_pipeline(req: FullPipelineRequest):
    """
    Run Stage 1 + Stage 2 in one call.

    If `layout_path` is provided in the request body (local file path to a
    GeoJSON or CSV), it is loaded before matching. Otherwise the previously
    uploaded layout (via /upload-layout) is used if available.
    """
    global _layout_store

    # Stage 1
    try:
        defects = run_pipeline(
            directory=req.path,
            conf=req.conf or 0.25,
            iou=req.iou or 0.45,
            min_frames=req.min_frames or 2,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        n_frames = len(_find_images(req.path))
    except Exception:
        n_frames = 0

    # Stage 2 — optionally load layout from path given in request
    if req.layout_path:
        try:
            with open(req.layout_path, "rb") as f:
                content = f.read()
            store = LayoutStore()
            if req.layout_path.lower().endswith(".csv"):
                store.load_csv(content)
            else:
                store.load_geojson(content)
            _layout_store = store
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to load layout_path: {exc}")

    if _layout_store is not None and _layout_store.panels:
        defects = _apply_layout(defects, _layout_store)

    scan_id = str(uuid.uuid4())[:8]
    resp = ScanResponse(
        scan_id=scan_id,
        total_frames=n_frames,
        defects_found=len(defects),
        defects=defects,
    )
    _scan_store[scan_id] = resp
    return resp


@app.get("/results/{scan_id}", response_model=ScanResponse)
def get_results(scan_id: str):
    if scan_id not in _scan_store:
        raise HTTPException(status_code=404, detail=f"Scan '{scan_id}' not found.")
    return _scan_store[scan_id]
