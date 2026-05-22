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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import OUTPUTS_DIR
from app.database import init_db
from app.layout_mapper import LayoutStore
from app.models import (
    DefectRecord,
    FullPipelineRequest,
    LayoutMapping,
    ScanRequest,
    ScanResponse,
)
from app.plant_router import router as plant_router
from app import state
from app.tracker_pipeline import _find_images, run_pipeline

os.makedirs(OUTPUTS_DIR, exist_ok=True)
init_db()

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

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

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
app.include_router(plant_router)

# Aliases to shared state (backwards compat for existing helpers)
def _get_scan_store():      return state.scan_store
def _get_layout_store():    return state.layout_store
def _set_layout_store(v):   state.layout_store = v


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

@app.get("/")
def serve_ui():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/health")
def health():
    return {"status": "ok", "layout_loaded": state.layout_store is not None and len(state.layout_store.panels) > 0}


@app.get("/scans")
def list_scans():
    """Return all scan IDs currently held in memory."""
    return list(state.scan_store.keys())


# ── Plant layout endpoints ──────────────────────────────────────────────────

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

@app.get("/plant/metadata")
def plant_metadata():
    path = os.path.join(_DATA_DIR, "plant_metadata.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Plant metadata not found. Run build_plant_layout.py first.")
    return FileResponse(path, media_type="application/json")


@app.get("/plant/geojson")
def plant_geojson():
    path = os.path.join(_DATA_DIR, "plant_layout.geojson")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Plant GeoJSON not found.")
    return FileResponse(path, media_type="application/json")


@app.get("/plant/panels")
def plant_panels():
    path = os.path.join(_DATA_DIR, "plant_panels.geojson")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Panel GeoJSON not found.")
    return FileResponse(path, media_type="application/json")


@app.get("/image")
def serve_image(path: str, x1: float = 0, y1: float = 0,
                x2: float = 0, y2: float = 0,
                cls: str = "", conf: float = 0):
    """
    Serve a thermal JPG annotated with a defect bounding box.
    path  — absolute or relative path to the JPG
    x1,y1,x2,y2 — bbox in pixels (skip annotation if all zero)
    cls   — class name for colour/label
    conf  — confidence for label
    """
    from fastapi.responses import StreamingResponse
    import io
    from PIL import Image, ImageDraw, ImageFont

    COLORS = {
        "hotspot":      (239, 68,  68),
        "bypass_diode": (249, 115, 22),
        "hot_region":   (234, 179,  8),
        "cold_region":  (59, 130, 246),
    }

    if not os.path.isabs(path):
        path = os.path.join(_DATA_DIR, "..", path)
    path = os.path.normpath(path)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Image not found: {path}")

    img = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(img)

    has_bbox = not (x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0)
    if has_bbox:
        color = COLORS.get(cls, (148, 163, 184))
        lw = max(2, int(img.width / 200))
        draw.rectangle([x1, y1, x2, y2], outline=color, width=lw)
        label = f"{cls.replace('_', ' ')} {conf*100:.0f}%" if cls else ""
        if label:
            pad = 4
            tw = len(label) * 7
            th = 14
            draw.rectangle([x1, y1 - th - pad*2, x1 + tw + pad*2, y1], fill=color)
            try:
                font = ImageFont.truetype("arial.ttf", 13)
            except Exception:
                font = ImageFont.load_default()
            draw.text((x1 + pad, y1 - th - pad), label, fill="white", font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/jpeg")


@app.get("/footprints")
def get_footprints(path: str):
    """
    Return a GeoJSON FeatureCollection of ground-projected image footprints.
    Each feature is the quadrilateral on the ground that the camera captured,
    computed by ray-tracing the 4 corner pixels using the image EXIF metadata.
    """
    from app.exif_parser import parse_frame
    from app.geolocator import pixel_to_gps

    try:
        frames = _find_images(path)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if not frames:
        raise HTTPException(status_code=404, detail=f"No images found in: {path}")

    features = []
    for frame_path in frames:
        try:
            meta = parse_frame(frame_path)
        except Exception:
            continue

        if not meta.valid_gps or meta.altitude_m <= 0:
            continue

        w, h = meta.image_w, meta.image_h
        # Ray-trace the 4 image corners to GPS coordinates
        corners = [
            pixel_to_gps(0, 0, meta),
            pixel_to_gps(w, 0, meta),
            pixel_to_gps(w, h, meta),
            pixel_to_gps(0, h, meta),
        ]
        # GeoJSON uses [lon, lat] order; close the ring
        ring = [[lon, lat] for lat, lon in corners]
        ring.append(ring[0])

        features.append({
            "type": "Feature",
            "properties": {
                "filename":     os.path.basename(frame_path),
                "altitude_m":   round(meta.altitude_m, 1),
                "gimbal_pitch": round(meta.gimbal_pitch_deg, 1),
                "flight_yaw":   round(meta.flight_yaw_deg, 1),
                "latitude":     round(meta.latitude, 6),
                "longitude":    round(meta.longitude, 6),
            },
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })

    return {"type": "FeatureCollection", "features": features, "total": len(features)}


@app.get("/center")
def get_center(path: str):
    """Return the GPS centroid of images in a directory. Reads first 20 frames for speed."""
    from app.exif_parser import parse_frame
    try:
        frames = _find_images(path)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not frames:
        raise HTTPException(status_code=404, detail=f"No images found in: {path}")

    lats, lons = [], []
    for fp in frames[:20]:
        try:
            meta = parse_frame(fp)
            if meta.valid_gps:
                lats.append(meta.latitude)
                lons.append(meta.longitude)
        except Exception:
            continue
    if not lats:
        raise HTTPException(status_code=422, detail="No valid GPS found in sampled images.")
    return {
        "latitude":  round(sum(lats) / len(lats), 6),
        "longitude": round(sum(lons) / len(lons), 6),
        "samples":   len(lats),
    }


@app.post("/scan", response_model=ScanResponse)
def scan(req: ScanRequest):
    """Stage 1: YOLO detection + ByteTrack + geolocation."""
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
    state.scan_store[scan_id] = resp
    return resp


@app.post("/upload-layout")
async def upload_layout(file: UploadFile = File(...)):
    """Upload a GeoJSON or CSV panel layout file. Replaces any previously loaded layout."""
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
    state.layout_store = store
    return {"panels_loaded": n, "filename": filename}


@app.post("/map/{scan_id}", response_model=ScanResponse)
def map_layout(scan_id: str):
    """Apply the currently loaded layout to an existing scan, assigning panel IDs to defects."""
    if scan_id not in state.scan_store:
        raise HTTPException(status_code=404, detail=f"Scan '{scan_id}' not found.")
    if state.layout_store is None or not state.layout_store.panels:
        raise HTTPException(status_code=422, detail="No layout loaded. POST /upload-layout first.")

    updated_scan = state.scan_store[scan_id].model_copy(update={
        "defects": _apply_layout(state.scan_store[scan_id].defects, state.layout_store)
    })
    state.scan_store[scan_id] = updated_scan
    return updated_scan


@app.post("/pipeline", response_model=ScanResponse)
def full_pipeline(req: FullPipelineRequest):
    """Stage 1 + Stage 2 in one call. layout_path optional in request body."""
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

    if req.layout_path:
        try:
            with open(req.layout_path, "rb") as f:
                content = f.read()
            store = LayoutStore()
            if req.layout_path.lower().endswith(".csv"):
                store.load_csv(content)
            else:
                store.load_geojson(content)
            state.layout_store = store
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to load layout_path: {exc}")

    if state.layout_store is not None and state.layout_store.panels:
        defects = _apply_layout(defects, state.layout_store)

    scan_id = str(uuid.uuid4())[:8]
    resp = ScanResponse(
        scan_id=scan_id,
        total_frames=n_frames,
        defects_found=len(defects),
        defects=defects,
    )
    state.scan_store[scan_id] = resp
    return resp


@app.get("/results/{scan_id}", response_model=ScanResponse)
def get_results(scan_id: str):
    if scan_id not in state.scan_store:
        raise HTTPException(status_code=404, detail=f"Scan '{scan_id}' not found.")
    return state.scan_store[scan_id]
