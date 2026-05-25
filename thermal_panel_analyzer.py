#!/usr/bin/env python3
"""
thermal_panel_analyzer.py
=========================
Solar PV Thermal Image Defect Detection Pipeline

Detects four defect classes in drone-captured thermal imagery:
  HOT_SPOT      — Localized high-temperature region on a single panel
  BYPASS_DIODE  — 1/3 or 2/3 of a panel uniformly elevated (shorted bypass diode)
  STRING_OFF    — Entire row/string warmer than the rest of the array
  PANEL_OFF     — Single panel uniformly colder than its string neighbors

Expected directory layout:
  data/<Project>/<Sequence>/image1.jpg
                             image2.tif
                             ...

Usage:
  # Single sequence
  python thermal_panel_analyzer.py -i data/SolarFarm_A/Seq01

  # All sequences in a project
  python thermal_panel_analyzer.py -i data/SolarFarm_A --recursive

  # Custom output directory
  python thermal_panel_analyzer.py -i data/SolarFarm_A/Seq01 -o results/

Dependencies:
  pip install opencv-python-headless numpy scipy
"""

import sys
import argparse
import csv
import logging
from pathlib import Path
from dataclasses import dataclass
from itertools import groupby
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    from scipy import ndimage as ndi  # noqa: F401  (used in future Gaussian fallback)
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


# ─── CONFIGURABLE PARAMETERS ──────────────────────────────────────────────────
# Edit these values to tune sensitivity for your specific camera and conditions.

# -- Temperature calibration for 16-bit radiometric TIFF/PNG -----------------
# Formula: temperature_celsius = raw_pixel_value * THERMAL_SCALE + THERMAL_OFFSET
# FLIR Zenmuse XT2 defaults — verify against your camera's datasheet.
THERMAL_SCALE:  float = 0.04       # Kelvin per raw LSB
THERMAL_OFFSET: float = -273.15    # converts Kelvin → Celsius

# -- Temperature range assumed for 8-bit pseudo-color exports -----------------
# Pixel 0 maps to PSEUDO_MIN °C; pixel 255 maps to PSEUDO_MAX °C.
# Set these to match the palette range shown in your camera software.
PSEUDO_COLOR_TEMP_MIN: float = 15.0   # °C at pixel value 0
PSEUDO_COLOR_TEMP_MAX: float = 80.0   # °C at pixel value 255

# -- Panel geometry filters ---------------------------------------------------
MIN_PANEL_AREA: int   = 800        # px² — smaller contours are noise or shadow
MAX_PANEL_AREA: int   = 100_000    # px² — larger contours are multi-panel blobs
PANEL_ASPECT_RATIO_MIN: float = 0.3   # height / width (landscape ≈ 0.5, portrait ≈ 1.8)
PANEL_ASPECT_RATIO_MAX: float = 4.0
PANEL_SOLIDITY_MIN:    float = 0.72   # contour_area / convex_hull_area; filters L-shapes

# -- Background masking -------------------------------------------------------
# Pixels whose temperature falls outside [LOW, HIGH] percentiles are masked out.
BG_PERCENTILE_LOW:  int = 15     # below this → sky reflection, deep shadow
BG_PERCENTILE_HIGH: int = 99     # above this → sun glint or sensor artifact
MORPH_KERNEL_SIZE:  int = 11     # morphological close kernel (px); fills panel interiors

# -- Hot spot detection -------------------------------------------------------
HOT_SPOT_DELTA_CELSIUS:     float = 15.0    # °C above panel mean to flag as hot spot
HOT_SPOT_MIN_AREA_FRACTION: float = 0.003   # minimum hot-spot size vs panel area
HOT_SPOT_MAX_AREA_FRACTION: float = 0.12    # above this → treat as bypass, not hot spot

# -- Bypass diode failure detection -------------------------------------------
BYPASS_DIODE_DELTA_CELSIUS: float = 8.0     # °C above panel mean for a hot section
BYPASS_DIODE_MAX_STD_NORM:  float = 0.08    # max normalised σ; "uniform" = low σ

# -- String off detection -----------------------------------------------------
STRING_OFF_DELTA_CELSIUS:   float = 12.0    # °C above array mean to flag a string
STRING_GROUP_TOLERANCE:     float = 0.08    # vertical tolerance to group panels into rows
                                            # (fraction of image height)

# -- Panel off detection ------------------------------------------------------
PANEL_OFF_DELTA_CELSIUS:    float = -10.0   # °C BELOW string mean to flag as off/cold
                                            # Must be negative.

# -- Confidence scoring -------------------------------------------------------
# Confidence score reaches 1.0 when anomaly = threshold × SATURATION_MULT.
CONFIDENCE_SATURATION_MULT: float = 3.0

# -- I/O settings -------------------------------------------------------------
SUPPORTED_EXTS  = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp'}
OUTPUT_SUBDIR   = 'analyzed'         # sub-folder written inside each sequence dir
REPORT_FILENAME = 'defect_report.csv'
FONT_SCALE      = 0.50               # annotation text size
ANNOT_THICKNESS = 2                  # defect rectangle line width


# ─── DATA STRUCTURES ──────────────────────────────────────────────────────────

@dataclass
class Panel:
    """One detected solar panel within the image."""
    contour:   np.ndarray
    bbox:      Tuple[int, int, int, int]    # x, y, w, h  (image coordinates)
    centroid:  Tuple[float, float]          # cx, cy
    area:      float                        # contour area in pixels²
    mean_temp: float                        # mean temperature of panel pixels (°C)
    max_temp:  float
    min_temp:  float
    string_id: int = -1                     # horizontal row index (0 = top)
    panel_id:  int = -1                     # position within its string (0 = left)


@dataclass
class Defect:
    """One detected defect anomaly."""
    defect_type: str                        # HOT_SPOT | BYPASS_DIODE | STRING_OFF | PANEL_OFF
    confidence:  float                      # 0.0 – 1.0
    severity:    str                        # LOW | MEDIUM | HIGH
    bbox:        Tuple[int, int, int, int]  # defect bounding box (image coordinates)
    panel_bbox:  Tuple[int, int, int, int]  # enclosing panel bounding box
    string_id:   int
    panel_id:    int                        # -1 for STRING_OFF (affects whole row)
    delta_temp:  float                      # temperature deviation that triggered detection
    notes:       str = ''


# BGR colors for each defect class
DEFECT_COLORS: Dict[str, Tuple[int, int, int]] = {
    'HOT_SPOT':     (0,   0,   255),   # red
    'BYPASS_DIODE': (0,  140,  255),   # orange
    'STRING_OFF':   (0,  215,  255),   # yellow
    'PANEL_OFF':    (255, 180,   0),   # teal-blue
}


# ─── IMAGE LOADING ────────────────────────────────────────────────────────────

def load_thermal_image(
    path: Path,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Load a thermal image and return (gray_u8, temp_map_f32).

    gray_u8   — 8-bit grayscale for morphological operations
    temp_map  — float32 estimated temperature map in Celsius

    Handles:
      16-bit single-channel TIFF/PNG  → radiometric calibration via THERMAL_SCALE/OFFSET
      8-bit grayscale                 → linear mapping to [PSEUDO_MIN, PSEUDO_MAX]
      8-bit RGB/pseudo-color          → red channel as temperature proxy (works well
                                        for ironbow and rainbow palettes)
    """
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None:
        logging.warning("Cannot read image: %s", path)
        return None, None

    if raw.ndim == 2:
        if raw.dtype == np.uint16:
            # True radiometric data — apply calibration
            temp_map = raw.astype(np.float32) * THERMAL_SCALE + THERMAL_OFFSET
        else:
            # 8-bit grayscale proxy
            temp_map = (raw.astype(np.float32) / 255.0 *
                        (PSEUDO_COLOR_TEMP_MAX - PSEUDO_COLOR_TEMP_MIN) +
                        PSEUDO_COLOR_TEMP_MIN)
        gray = cv2.normalize(raw, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)

    elif raw.ndim == 3:
        if raw.dtype == np.uint16:
            ch = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
            temp_map = ch.astype(np.float32) * THERMAL_SCALE + THERMAL_OFFSET
            gray = cv2.normalize(ch, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
        else:
            # 8-bit pseudo-color export: the red channel increases monotonically
            # from cold (dark blue) to hot (white/yellow) in most FLIR palettes.
            red = raw[:, :, 2].astype(np.float32)
            temp_map = (red / 255.0 *
                        (PSEUDO_COLOR_TEMP_MAX - PSEUDO_COLOR_TEMP_MIN) +
                        PSEUDO_COLOR_TEMP_MIN)
            gray = raw[:, :, 2]   # same channel, uint8
    else:
        logging.warning("Unexpected image dimensions (%dD): %s", raw.ndim, path)
        return None, None

    return gray, temp_map


def load_bgr(path: Path, gray_fallback: np.ndarray) -> np.ndarray:
    """Load BGR color image for annotation output; fall back to gray→BGR."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if raw is not None:
            g8 = cv2.normalize(raw, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
            if g8.ndim == 3:
                g8 = cv2.cvtColor(g8, cv2.COLOR_BGR2GRAY)
            img = cv2.cvtColor(g8, cv2.COLOR_GRAY2BGR)
        else:
            img = cv2.cvtColor(gray_fallback, cv2.COLOR_GRAY2BGR)
    return img


# ─── BACKGROUND MASKING ───────────────────────────────────────────────────────

def create_panel_mask(temp_map: np.ndarray) -> np.ndarray:
    """
    Return a binary mask (uint8, 255 = panel region, 0 = background).

    Algorithm:
      1. Temperature percentile thresholding — keeps mid-to-high range pixels
         (panels are warmer than grass/sky under operating conditions)
      2. Morphological closing — fills the interior of each panel rectangle
      3. Small-blob removal — discards noise below half the minimum panel size
    """
    low  = np.percentile(temp_map, BG_PERCENTILE_LOW)
    high = np.percentile(temp_map, BG_PERCENTILE_HIGH)
    temp_mask = np.where(
        (temp_map >= low) & (temp_map <= high), np.uint8(255), np.uint8(0)
    )

    k = cv2.getStructuringElement(
        cv2.MORPH_RECT, (MORPH_KERNEL_SIZE, MORPH_KERNEL_SIZE)
    )
    closed = cv2.morphologyEx(temp_mask, cv2.MORPH_CLOSE, k, iterations=2)

    cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros_like(closed)
    for c in cnts:
        if cv2.contourArea(c) >= MIN_PANEL_AREA * 0.4:
            cv2.drawContours(mask, [c], -1, 255, cv2.FILLED)

    return mask


# ─── PANEL SEGMENTATION ───────────────────────────────────────────────────────

def segment_panels(mask: np.ndarray, temp_map: np.ndarray) -> List[Panel]:
    """
    Detect individual solar panels from the binary mask.

    Steps:
      1. Light erosion separates adjacent panels that touch edge-to-edge
      2. Contour detection with area / aspect-ratio / solidity filters
      3. Temperature statistics extracted per panel
      4. Panels grouped into horizontal strings by y-centroid clustering
    """
    # Separate panels that share a border after masking
    sep_k = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    separated = cv2.erode(mask, sep_k, iterations=1)

    cnts, _ = cv2.findContours(
        separated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    panels: List[Panel] = []

    for cnt in cnts:
        area = cv2.contourArea(cnt)
        if not (MIN_PANEL_AREA <= area <= MAX_PANEL_AREA):
            continue

        px, py, pw, ph = cv2.boundingRect(cnt)
        aspect = ph / max(pw, 1)
        if not (PANEL_ASPECT_RATIO_MIN <= aspect <= PANEL_ASPECT_RATIO_MAX):
            continue

        hull_area = cv2.contourArea(cv2.convexHull(cnt))
        if hull_area == 0 or area / hull_area < PANEL_SOLIDITY_MIN:
            continue

        # Build per-panel temperature mask and extract pixel values
        roi_mask = np.zeros(mask.shape, np.uint8)
        cv2.drawContours(roi_mask, [cnt], -1, 255, cv2.FILLED)
        pixels = temp_map[roi_mask == 255]
        if len(pixels) == 0:
            continue

        panels.append(Panel(
            contour   = cnt,
            bbox      = (px, py, pw, ph),
            centroid  = (px + pw / 2.0, py + ph / 2.0),
            area      = area,
            mean_temp = float(np.mean(pixels)),
            max_temp  = float(np.max(pixels)),
            min_temp  = float(np.min(pixels)),
        ))

    _assign_string_ids(panels, mask.shape[0])
    return panels


def _assign_string_ids(panels: List[Panel], img_height: int) -> None:
    """
    Cluster panels into horizontal strings by y-centroid proximity.
    Assigns string_id (row index, top→bottom) and panel_id (column index,
    left→right) in-place.
    """
    if not panels:
        return

    tol = STRING_GROUP_TOLERANCE * img_height
    sorted_y = sorted(panels, key=lambda p: p.centroid[1])

    sid, ref_y = 0, sorted_y[0].centroid[1]
    for p in sorted_y:
        if p.centroid[1] - ref_y > tol:
            sid  += 1
            ref_y = p.centroid[1]
        p.string_id = sid

    # Within each string, assign panel_id left→right
    sorted_all = sorted(panels, key=lambda p: (p.string_id, p.centroid[0]))
    for _sid, grp in groupby(sorted_all, key=lambda p: p.string_id):
        for pid, p in enumerate(grp):
            p.panel_id = pid


# ─── DEFECT DETECTION ─────────────────────────────────────────────────────────

def _score(delta: float, threshold: float) -> Tuple[float, str]:
    """
    Normalised confidence score [0.0, 1.0] and severity label.
    Score saturates at 1.0 when delta reaches threshold × CONFIDENCE_SATURATION_MULT.
    """
    raw = min(1.0, abs(delta) / max(abs(threshold) * CONFIDENCE_SATURATION_MULT, 1e-9))
    severity = 'HIGH' if raw >= 0.75 else ('MEDIUM' if raw >= 0.40 else 'LOW')
    return round(raw, 3), severity


# ── Hot Spot ─────────────────────────────────────────────────────────────────

def detect_hot_spots(panel: Panel, temp_map: np.ndarray) -> List[Defect]:
    """
    Detect small, intensely hot regions within a single panel.

    A hot spot is characterised by:
      - Peak temperature ≥ panel_mean + HOT_SPOT_DELTA_CELSIUS
      - Area between HOT_SPOT_MIN/MAX_AREA_FRACTION of the panel area
        (too large → likely a bypass diode pattern, not a hot spot)
    """
    x, y, w, h = panel.bbox
    roi = temp_map[y:y + h, x:x + w]
    if roi.size == 0:
        return []

    thresh = panel.mean_temp + HOT_SPOT_DELTA_CELSIUS
    hot_mask = np.where(roi >= thresh, np.uint8(255), np.uint8(0))

    # Remove single-pixel noise before labelling
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    hot_mask = cv2.morphologyEx(hot_mask, cv2.MORPH_OPEN, k)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(hot_mask)
    panel_area = w * h
    defects: List[Defect] = []

    for i in range(1, n):  # label 0 is background
        blob_area = int(stats[i, cv2.CC_STAT_AREA])
        if not (HOT_SPOT_MIN_AREA_FRACTION * panel_area
                <= blob_area
                <= HOT_SPOT_MAX_AREA_FRACTION * panel_area):
            continue

        bx = int(stats[i, cv2.CC_STAT_LEFT])
        by = int(stats[i, cv2.CC_STAT_TOP])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])

        peak  = float(np.max(roi[labels == i]))
        delta = peak - panel.mean_temp
        conf, sev = _score(delta, HOT_SPOT_DELTA_CELSIUS)

        defects.append(Defect(
            defect_type = 'HOT_SPOT',
            confidence  = conf,
            severity    = sev,
            bbox        = (x + bx, y + by, bw, bh),
            panel_bbox  = panel.bbox,
            string_id   = panel.string_id,
            panel_id    = panel.panel_id,
            delta_temp  = round(delta, 2),
            notes       = f"Peak {peak:.1f}°C, panel mean {panel.mean_temp:.1f}°C",
        ))

    return defects


# ── Bypass Diode Failure ──────────────────────────────────────────────────────

def detect_bypass_diode(panel: Panel, temp_map: np.ndarray) -> List[Defect]:
    """
    Detect a shorted bypass diode: one contiguous section (1/3 or 2/3 of the
    panel along its longer axis) shows a uniform, elevated temperature.

    Each standard 60/72-cell panel has three bypass diodes protecting 20/24 cells
    each, so a failure elevates exactly one third of the panel uniformly.
    """
    x, y, w, h = panel.bbox
    roi = temp_map[y:y + h, x:x + w]
    if roi.size == 0:
        return []

    # Divide along the longer dimension
    along_cols = (w >= h)
    dim        = w if along_cols else h
    third      = max(1, dim // 3)

    temp_range = max(panel.max_temp - panel.min_temp, 1.0)
    sections   = []
    for i in range(3):
        s = i * third
        e = (i + 1) * third if i < 2 else dim
        sec = roi[:, s:e] if along_cols else roi[s:e, :]
        sections.append({
            'idx':  i,
            'mean': float(np.mean(sec)),
            'std':  float(np.std(sec)) / temp_range,
            'start': s, 'end': e,
        })

    # Hot = significantly warm AND internally uniform (low std)
    hot_idx = [
        s['idx'] for s in sections
        if (s['mean'] - panel.mean_temp >= BYPASS_DIODE_DELTA_CELSIUS and
            s['std'] <= BYPASS_DIODE_MAX_STD_NORM)
    ]
    if not hot_idx:
        return []

    # Hot sections must be contiguous (e.g. [0,1] or [1] — not [0,2])
    hi = sorted(hot_idx)
    if len(hi) > 1 and hi[-1] - hi[0] != len(hi) - 1:
        return []

    coverage = len(hi) / 3.0
    if not (0.28 <= coverage <= 0.72):    # guard: only 1/3 or 2/3 is valid
        return []

    start_pos = sections[hi[0]]['start']
    end_pos   = sections[hi[-1]]['end']
    avg_delta = float(np.mean([sections[i]['mean'] - panel.mean_temp for i in hi]))
    conf, sev = _score(avg_delta, BYPASS_DIODE_DELTA_CELSIUS)

    dbbox = (
        (x + start_pos, y, end_pos - start_pos, h) if along_cols
        else (x, y + start_pos, w, end_pos - start_pos)
    )

    return [Defect(
        defect_type = 'BYPASS_DIODE',
        confidence  = conf,
        severity    = sev,
        bbox        = dbbox,
        panel_bbox  = panel.bbox,
        string_id   = panel.string_id,
        panel_id    = panel.panel_id,
        delta_temp  = round(avg_delta, 2),
        notes       = (f"Hot thirds {hi}, coverage {coverage:.0%}, "
                       f"ΔT {avg_delta:.1f}°C above panel mean"),
    )]


# ── String Off ────────────────────────────────────────────────────────────────

def detect_string_off(all_panels: List[Panel]) -> List[Defect]:
    """
    Flag entire strings that are significantly warmer than the array average.

    A hot string typically indicates a DC-side fault (disconnected string
    inverter, MCB open) causing the string to act as a load instead of a source.
    Requires at least two strings to make a meaningful comparison.
    """
    if len(all_panels) < 2:
        return []

    by_string: Dict[int, List[float]] = {}
    for p in all_panels:
        by_string.setdefault(p.string_id, []).append(p.mean_temp)

    if len(by_string) < 2:
        return []

    string_avg = {sid: float(np.mean(t)) for sid, t in by_string.items()}
    array_mean = float(np.mean(list(string_avg.values())))
    defects: List[Defect] = []

    for sid, avg in string_avg.items():
        delta = avg - array_mean
        if delta < STRING_OFF_DELTA_CELSIUS:
            continue

        sp  = [p for p in all_panels if p.string_id == sid]
        sx  = min(p.bbox[0]            for p in sp)
        sy  = min(p.bbox[1]            for p in sp)
        sx2 = max(p.bbox[0] + p.bbox[2] for p in sp)
        sy2 = max(p.bbox[1] + p.bbox[3] for p in sp)

        conf, sev = _score(delta, STRING_OFF_DELTA_CELSIUS)
        defects.append(Defect(
            defect_type = 'STRING_OFF',
            confidence  = conf,
            severity    = sev,
            bbox        = (sx, sy, sx2 - sx, sy2 - sy),
            panel_bbox  = (sx, sy, sx2 - sx, sy2 - sy),
            string_id   = sid,
            panel_id    = -1,
            delta_temp  = round(delta, 2),
            notes       = (f"String mean {avg:.1f}°C, "
                           f"array mean {array_mean:.1f}°C, ΔT {delta:.1f}°C"),
        ))

    return defects


# ── Panel Off ─────────────────────────────────────────────────────────────────

def detect_panel_off(panel: Panel, all_panels: List[Panel]) -> List[Defect]:
    """
    Flag a panel that is uniformly colder than its string neighbors.

    A cold panel is not generating power (e.g. open-circuit, shade, soiling)
    and therefore lacks the resistive heating seen in working panels.
    """
    neighbors = [p for p in all_panels
                 if p.string_id == panel.string_id and p.panel_id != panel.panel_id]
    if not neighbors:
        return []

    neighbor_mean = float(np.mean([p.mean_temp for p in neighbors]))
    delta = panel.mean_temp - neighbor_mean   # negative means this panel is colder

    if delta > PANEL_OFF_DELTA_CELSIUS:       # threshold is negative
        return []

    conf, sev = _score(delta, PANEL_OFF_DELTA_CELSIUS)
    return [Defect(
        defect_type = 'PANEL_OFF',
        confidence  = conf,
        severity    = sev,
        bbox        = panel.bbox,
        panel_bbox  = panel.bbox,
        string_id   = panel.string_id,
        panel_id    = panel.panel_id,
        delta_temp  = round(delta, 2),
        notes       = (f"Panel {panel.mean_temp:.1f}°C vs "
                       f"neighbors {neighbor_mean:.1f}°C, ΔT {delta:.1f}°C"),
    )]


# ── Detection Runner ──────────────────────────────────────────────────────────

def run_all_detectors(panels: List[Panel], temp_map: np.ndarray) -> List[Defect]:
    """
    Execute the full detection stack on a set of segmented panels.

    Detection order:
      1. STRING_OFF  — needs full array context
      2. Per-panel HOT_SPOT, BYPASS_DIODE, PANEL_OFF

    Panels belonging to an already-flagged STRING_OFF are skipped for per-panel
    analysis to avoid redundant sub-annotations.  Remove the guard (string_off_ids)
    if you want both levels of detail simultaneously.
    """
    if not panels:
        return []

    all_defects: List[Defect] = []

    string_defects = detect_string_off(panels)
    all_defects.extend(string_defects)
    string_off_ids = {d.string_id for d in string_defects}

    for panel in panels:
        if panel.string_id in string_off_ids:
            continue

        hot_spots = detect_hot_spots(panel, temp_map)
        all_defects.extend(hot_spots)

        # Skip bypass check if hot spots already dominate this panel
        flagged_panels = {(d.string_id, d.panel_id) for d in hot_spots}
        if (panel.string_id, panel.panel_id) not in flagged_panels:
            all_defects.extend(detect_bypass_diode(panel, temp_map))

        all_defects.extend(detect_panel_off(panel, panels))

    return all_defects


# ─── VISUALIZATION ────────────────────────────────────────────────────────────

def annotate(
    color_img: np.ndarray,
    panels:    List[Panel],
    defects:   List[Defect],
) -> np.ndarray:
    """
    Draw panel outlines and color-coded defect bounding boxes on a copy of the image.

    - Thin dark outlines with S/P index labels: all detected panels
    - Thick colored rectangles + labels: each detected defect
    - Legend: top-right corner with defect type → color mapping
    """
    out = color_img.copy()

    for p in panels:
        x, y, w, h = p.bbox
        cv2.rectangle(out, (x, y), (x + w, y + h), (60, 80, 60), 1)
        cv2.putText(out, f"S{p.string_id}P{p.panel_id}",
                    (x + 2, y + 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.32, (60, 80, 60), 1, cv2.LINE_AA)

    for d in defects:
        color = DEFECT_COLORS.get(d.defect_type, (255, 255, 255))
        dx, dy, dw, dh = d.bbox
        cv2.rectangle(out, (dx, dy), (dx + dw, dy + dh), color, ANNOT_THICKNESS)

        label = f"{d.defect_type}  {d.severity}  {d.confidence:.0%}"
        (tw, th), bl = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, 1
        )
        label_y = max(dy - 4, th + 4)
        cv2.rectangle(out,
                      (dx, label_y - th - bl),
                      (dx + tw, label_y + bl),
                      color, cv2.FILLED)
        cv2.putText(out, label, (dx, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE,
                    (0, 0, 0), 1, cv2.LINE_AA)

    _draw_legend(out)
    return out


def _draw_legend(img: np.ndarray) -> None:
    """Semi-transparent legend in the top-right corner."""
    items  = list(DEFECT_COLORS.items())
    lh     = len(items) * 22 + 12
    lw     = 220
    h, w   = img.shape[:2]
    lx, ly = w - lw - 10, 10

    overlay = img.copy()
    cv2.rectangle(overlay, (lx - 4, ly - 4),
                  (lx + lw, ly + lh), (20, 20, 20), cv2.FILLED)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)

    for i, (label, color) in enumerate(items):
        iy = ly + 14 + i * 22
        cv2.rectangle(img, (lx, iy - 10), (lx + 16, iy + 4), color, cv2.FILLED)
        cv2.putText(img, label, (lx + 22, iy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (210, 210, 210),
                    1, cv2.LINE_AA)


# ─── CSV REPORTING ────────────────────────────────────────────────────────────

_CSV_FIELDS = [
    'project', 'sequence', 'image_name',
    'defect_type', 'severity', 'confidence',
    'string_id', 'panel_id',
    'bbox_x', 'bbox_y', 'bbox_w', 'bbox_h',
    'delta_temp_c', 'notes',
]


def append_csv(report_path: Path, rows: List[dict]) -> None:
    """Append defect rows to the CSV report; writes header if the file is new."""
    write_header = not report_path.exists()
    with open(report_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction='ignore')
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


# ─── PIPELINE ORCHESTRATION ───────────────────────────────────────────────────

def process_image(
    img_path:    Path,
    out_dir:     Path,
    report_path: Path,
    project:     str,
    sequence:    str,
) -> int:
    """
    Run the full pipeline on a single image.
    Writes an annotated JPEG to out_dir and appends defects to the CSV report.
    Returns the number of defects detected.
    """
    logging.info("  Processing: %s", img_path.name)

    gray, temp_map = load_thermal_image(img_path)
    if gray is None:
        return 0

    color  = load_bgr(img_path, gray)
    mask   = create_panel_mask(temp_map)
    panels = segment_panels(mask, temp_map)

    if not panels:
        logging.info("    No panels detected — saving debug mask.")
        debug = color.copy()
        debug[mask == 0] = (debug[mask == 0] * 0.3).astype(np.uint8)
        cv2.imwrite(str(out_dir / f"nomask_{img_path.stem}.jpg"), debug)
        return 0

    n_strings = len({p.string_id for p in panels})
    logging.info("    %d panels across %d string(s)", len(panels), n_strings)

    defects = run_all_detectors(panels, temp_map)
    logging.info("    Defects: %s", _tally(defects))

    annotated = annotate(color, panels, defects)
    cv2.imwrite(str(out_dir / f"analyzed_{img_path.stem}.jpg"), annotated)

    if defects:
        append_csv(report_path, [dict(
            project      = project,
            sequence     = sequence,
            image_name   = img_path.name,
            defect_type  = d.defect_type,
            severity     = d.severity,
            confidence   = d.confidence,
            string_id    = d.string_id,
            panel_id     = d.panel_id,
            bbox_x       = d.bbox[0],
            bbox_y       = d.bbox[1],
            bbox_w       = d.bbox[2],
            bbox_h       = d.bbox[3],
            delta_temp_c = d.delta_temp,
            notes        = d.notes,
        ) for d in defects])

    return len(defects)


def _tally(defects: List[Defect]) -> str:
    counts: Dict[str, int] = {}
    for d in defects:
        counts[d.defect_type] = counts.get(d.defect_type, 0) + 1
    return ', '.join(f"{k}:{v}" for k, v in counts.items()) or 'none'


def process_sequence(
    seq_dir:     Path,
    out_root:    Path,
    report_path: Path,
    project:     str,
) -> Tuple[int, int]:
    """Process all thermal images in one sequence directory."""
    seq = seq_dir.name
    logging.info("\n%s\nSequence: %s  |  Project: %s\n%s",
                 '─' * 58, seq, project, '─' * 58)

    images = sorted(
        f for f in seq_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
    )
    if not images:
        logging.warning("No supported images found in: %s", seq_dir)
        return 0, 0

    logging.info("%d image(s) found", len(images))
    out_dir = out_root / project / seq / OUTPUT_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)

    n_imgs = n_defs = 0
    for img in images:
        try:
            n_defs += process_image(img, out_dir, report_path, project, seq)
            n_imgs  += 1
        except Exception as exc:
            logging.error("Failed on %s: %s", img.name, exc, exc_info=True)

    logging.info("Sequence done: %d images, %d defects total", n_imgs, n_defs)
    return n_imgs, n_defs


def process_project(
    proj_dir:    Path,
    out_root:    Path,
    report_path: Path,
) -> None:
    """Iterate all sequence subdirectories inside a project directory."""
    proj = proj_dir.name
    seqs = sorted(d for d in proj_dir.iterdir() if d.is_dir())

    if not seqs:
        # No subdirectories → treat the project dir itself as a single sequence
        process_sequence(proj_dir, out_root, report_path, proj)
        return

    total_imgs = total_defs = 0
    for seq_dir in seqs:
        ni, nd = process_sequence(seq_dir, out_root, report_path, proj)
        total_imgs += ni
        total_defs += nd

    logging.info("\n%s\nProject '%s': %d images, %d defects\n%s",
                 '=' * 58, proj, total_imgs, total_defs, '=' * 58)


# ─── CLI ENTRY POINT ──────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='thermal_panel_analyzer',
        description='Solar PV Thermal Image Defect Detection Pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python thermal_panel_analyzer.py -i data/SolarFarm_A/Seq01
  python thermal_panel_analyzer.py -i data/SolarFarm_A --recursive
  python thermal_panel_analyzer.py -i data/SolarFarm_A/Seq01 -o results/
""",
    )
    p.add_argument('-i', '--input', required=True,
                   help='Sequence directory, or (with -r) project directory')
    p.add_argument('-o', '--output', default='output',
                   help='Root output directory (default: ./output)')
    p.add_argument('-r', '--recursive', action='store_true',
                   help='Input is a project dir; recurse into all sequence subdirs')
    p.add_argument('--report', default=None,
                   help='CSV report path (default: <output>/defect_report.csv)')
    p.add_argument('--log-level', default='INFO',
                   choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    return p


def main() -> None:
    args = _build_parser().parse_args()

    logging.basicConfig(
        level   = getattr(logging, args.log_level),
        format  = '%(asctime)s  %(levelname)-8s  %(message)s',
        datefmt = '%H:%M:%S',
    )

    inp = Path(args.input)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    report = Path(args.report) if args.report else out / REPORT_FILENAME

    if not inp.exists():
        logging.error("Input path does not exist: %s", inp)
        sys.exit(1)
    if not inp.is_dir():
        logging.error("Input must be a directory: %s", inp)
        sys.exit(1)

    if args.recursive:
        process_project(inp, out, report)
    else:
        project = inp.parent.name or inp.name
        process_sequence(inp, out, report, project)

    logging.info("Report saved to: %s", report)
    logging.info("Done.")


if __name__ == '__main__':
    main()
