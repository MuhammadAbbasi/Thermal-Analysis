from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class EstimatedCoordinates(BaseModel):
    latitude: float
    longitude: float
    quadcopter_height_m: float


class LayoutMapping(BaseModel):
    matched_panel_id: str
    distance_to_panel_center_m: float


class DefectRecord(BaseModel):
    defect_id: str
    class_name: str
    confidence: float
    frames_tracked: int
    estimated_coordinates: EstimatedCoordinates
    layout_mapping: Optional[LayoutMapping] = None
    bbox_avg: Optional[List[float]] = Field(None, description="[x1,y1,x2,y2] averaged across frames")
    source_images: Optional[List[str]] = None


class ScanRequest(BaseModel):
    path: str = Field(..., description="Directory path containing .jpg thermal images, e.g. /data/SP3/2026_05_13")
    conf: Optional[float] = 0.25
    iou: Optional[float] = 0.45
    min_frames: Optional[int] = 2


class ScanResponse(BaseModel):
    scan_id: str
    total_frames: int
    defects_found: int
    defects: List[DefectRecord]


class MapRequest(BaseModel):
    scan_id: str


class FullPipelineRequest(BaseModel):
    path: str
    conf: Optional[float] = 0.25
    iou: Optional[float] = 0.45
    min_frames: Optional[int] = 2
    layout_path: Optional[str] = Field(None, description="Local path to a GeoJSON or CSV panel layout file")
