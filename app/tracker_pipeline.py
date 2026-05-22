"""
Stage 1 — Detection, tracking and geolocation pipeline.

Workflow
--------
1. Collect all .jpg frames from the given directory (sorted by filename).
2. For each frame: parse EXIF/XMP metadata, run YOLOv8 inference with
   ByteTrack (persist=True keeps track state across frames).
3. Accumulate per-track bounding boxes, confidences and source images.
4. After all frames, consolidate each track into one DefectRecord:
   - average confidence, bbox, and geolocated GPS coordinate.
   - skip tracks seen in fewer than min_frames frames.
"""
from __future__ import annotations

import os
import uuid
from collections import defaultdict
from pathlib import Path
from typing import List

import numpy as np

from app.config import CLASS_NAMES, CONF_THRESHOLD, IOU_THRESHOLD, MIN_FRAMES_TRACKED, MODEL_WEIGHTS
from app.exif_parser import parse_frame, FrameMeta
from app.geolocator import pixel_to_gps
from app.models import DefectRecord, EstimatedCoordinates


def _find_images(directory: str) -> List[str]:
    """Recursively find all .jpg/.JPG files under directory, sorted by filename."""
    p = Path(directory)
    files = sorted(
        [str(f) for f in p.rglob("*.JPG")] +
        [str(f) for f in p.rglob("*.jpg")]
    )
    return list(dict.fromkeys(files))  # deduplicate, preserve order


def run_pipeline(
    directory: str,
    conf: float = CONF_THRESHOLD,
    iou: float  = IOU_THRESHOLD,
    min_frames: int = MIN_FRAMES_TRACKED,
    model_path: str = MODEL_WEIGHTS,
) -> List[DefectRecord]:
    """
    Run full Stage-1 pipeline on a directory of thermal images.
    Returns a list of consolidated DefectRecord objects.
    """
    from ultralytics import YOLO

    frames = _find_images(directory)
    if not frames:
        raise FileNotFoundError(f"No .jpg images found in: {directory}")

    model = YOLO(model_path)

    # Per-track accumulators
    track_classes:  dict[int, list[int]]         = defaultdict(list)
    track_confs:    dict[int, list[float]]        = defaultdict(list)
    track_bboxes:   dict[int, list[list[float]]]  = defaultdict(list)
    track_metas:    dict[int, list[FrameMeta]]    = defaultdict(list)
    track_centers:  dict[int, list[tuple]]        = defaultdict(list)
    track_sources:  dict[int, list[str]]          = defaultdict(list)

    print(f"[AutoThermo] Processing {len(frames)} frames from: {directory}")

    for frame_path in frames:
        meta = parse_frame(frame_path)

        results = model.track(
            source=frame_path,
            tracker="bytetrack.yaml",
            persist=True,
            conf=conf,
            iou=iou,
            verbose=False,
        )

        if not results or results[0].boxes is None:
            continue

        boxes = results[0].boxes
        if boxes.id is None:
            continue

        track_ids = boxes.id.cpu().numpy().astype(int)
        xyxy      = boxes.xyxy.cpu().numpy()
        confs_arr = boxes.conf.cpu().numpy()
        cls_arr   = boxes.cls.cpu().numpy().astype(int)

        for tid, box, cf, cl in zip(track_ids, xyxy, confs_arr, cls_arr):
            x1, y1, x2, y2 = box
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            track_classes[tid].append(int(cl))
            track_confs[tid].append(float(cf))
            track_bboxes[tid].append([float(x1), float(y1), float(x2), float(y2)])
            track_metas[tid].append(meta)
            track_centers[tid].append((cx, cy))
            track_sources[tid].append(frame_path)

    defects: List[DefectRecord] = []
    counter = 1

    for tid, classes in track_classes.items():
        n_frames = len(classes)
        if n_frames < min_frames:
            continue

        dominant_class = int(np.bincount(classes).argmax())
        class_name     = CLASS_NAMES.get(dominant_class, f"class_{dominant_class}")
        avg_conf       = float(np.mean(track_confs[tid]))

        bboxes_arr = np.array(track_bboxes[tid])
        avg_bbox   = bboxes_arr.mean(axis=0).tolist()

        # Use highest-confidence frame for geolocation
        best_idx  = int(np.argmax(track_confs[tid]))
        best_meta = track_metas[tid][best_idx]
        best_cx, best_cy = track_centers[tid][best_idx]

        if best_meta.valid_gps:
            lat, lon = pixel_to_gps(best_cx, best_cy, best_meta)
        else:
            lat, lon = best_meta.latitude, best_meta.longitude

        defect = DefectRecord(
            defect_id=f"DEF-{counter:04d}",
            class_name=class_name,
            confidence=round(avg_conf, 4),
            frames_tracked=n_frames,
            estimated_coordinates=EstimatedCoordinates(
                latitude=round(lat, 7),
                longitude=round(lon, 7),
                quadcopter_height_m=round(best_meta.altitude_m, 2),
            ),
            bbox_avg=[round(v, 1) for v in avg_bbox],
            source_images=list(dict.fromkeys(track_sources[tid])),
        )
        defects.append(defect)
        counter += 1

    print(f"[AutoThermo] Stage 1 complete — {len(defects)} defects consolidated")
    return defects
