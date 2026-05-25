# Thermal Panel Analyzer

**File:** `thermal_panel_analyzer.py`  
**Language:** Python 3  
**Purpose:** Detect solar PV defects in drone-captured thermal images using classical computer vision (OpenCV + NumPy). No deep learning required.

---

## What This Script Does

Runs a multi-stage pipeline on thermal images of solar PV plants:

1. Loads each image and converts pixel values to an estimated temperature map (°C)
2. Masks out background (grass, soil, sky) — keeps only panel regions
3. Segments individual panels and groups them into horizontal strings
4. Runs four independent defect detectors
5. Writes annotated JPEG outputs and a cumulative CSV report

---

## Directory Contract

Images must follow this layout:

```
data/
  <Project_Name>/
    <Sequence_Name>/
      image1.jpg
      image2.tif
      ...
```

Outputs are written to:

```
output/
  <Project_Name>/
    <Sequence_Name>/
      analyzed/
        analyzed_<stem>.jpg   ← annotated image
        nomask_<stem>.jpg     ← debug view when no panels detected
  defect_report.csv           ← cumulative across all runs
```

---

## CLI

```bash
# Single sequence
python thermal_panel_analyzer.py -i data/SolarFarm_A/Seq01

# All sequences in a project
python thermal_panel_analyzer.py -i data/SolarFarm_A --recursive

# Custom output + verbose logging
python thermal_panel_analyzer.py -i data/SolarFarm_A/Seq01 -o results/ --log-level DEBUG
```

| Flag | Default | Description |
|---|---|---|
| `-i / --input` | required | Sequence dir or project dir (with `-r`) |
| `-o / --output` | `./output` | Root output directory |
| `-r / --recursive` | false | Iterate all sequence subdirs inside a project dir |
| `--report` | `<output>/defect_report.csv` | Override CSV path |
| `--log-level` | `INFO` | `DEBUG \| INFO \| WARNING \| ERROR` |

---

## Image Format Support

| Format | How it's handled |
|---|---|
| **16-bit TIFF/PNG** (raw radiometric) | `temp = pixel × THERMAL_SCALE + THERMAL_OFFSET` (default: FLIR Zenmuse XT2 calibration) |
| **8-bit grayscale** | Linear map: pixel 0 → `PSEUDO_COLOR_TEMP_MIN`, pixel 255 → `PSEUDO_COLOR_TEMP_MAX` |
| **8-bit RGB / pseudo-color** | Red channel used as temperature proxy (monotonic in FLIR ironbow/rainbow palettes) |

---

## Pipeline Stages

### Stage 1 — Background Masking (`create_panel_mask`)

- Temperature percentile threshold: keeps pixels in `[BG_PERCENTILE_LOW, BG_PERCENTILE_HIGH]` range
- Morphological `CLOSE` with `MORPH_KERNEL_SIZE × MORPH_KERNEL_SIZE` kernel — fills panel interiors
- Drops contours below `MIN_PANEL_AREA × 0.4` px² (noise removal)
- Returns a uint8 binary mask (255 = panel, 0 = background)

### Stage 2 — Panel Segmentation (`segment_panels`)

- Light `ERODE` (5×5 kernel, 1 iteration) separates adjacent panels that share a border
- Contour detection on eroded mask
- Per-contour filters:
  - `MIN_PANEL_AREA ≤ area ≤ MAX_PANEL_AREA`
  - `PANEL_ASPECT_RATIO_MIN ≤ height/width ≤ PANEL_ASPECT_RATIO_MAX`
  - `area / convex_hull_area ≥ PANEL_SOLIDITY_MIN` (rejects L-shapes, shadows)
- Temperature stats (`mean`, `max`, `min`) extracted per panel from the original mask
- Panels sorted into horizontal **strings** by y-centroid clustering (`STRING_GROUP_TOLERANCE × image_height` vertical tolerance)
- Each panel gets a `string_id` (row, top→bottom) and `panel_id` (column, left→right)

### Stage 3 — Defect Detection

Four independent detectors run in this order:

#### `detect_string_off(all_panels)`
- Compute mean temperature per string
- Compute overall array mean across all strings (requires ≥ 2 strings)
- Flag any string where `string_mean − array_mean ≥ STRING_OFF_DELTA_CELSIUS`
- Defect bbox = union of all panel bboxes in that string
- Panels in flagged strings are **skipped** for per-panel detection (configurable)

#### `detect_hot_spots(panel, temp_map)`
- Threshold panel ROI at `panel.mean_temp + HOT_SPOT_DELTA_CELSIUS`
- Morphological `OPEN` (3×3 ellipse) removes single-pixel noise
- `connectedComponentsWithStats` labels remaining blobs
- Keep blobs where `HOT_SPOT_MIN_AREA_FRACTION × panel_area ≤ blob_area ≤ HOT_SPOT_MAX_AREA_FRACTION × panel_area`
- Each valid blob → one `HOT_SPOT` defect; `delta_temp = peak − panel.mean_temp`

#### `detect_bypass_diode(panel, temp_map)`
- Divide panel into thirds along its **longer axis**
- Per-third: compute `mean` and `std / temp_range` (normalised uniformity)
- Flag sections where `section_mean − panel_mean ≥ BYPASS_DIODE_DELTA_CELSIUS` AND `norm_std ≤ BYPASS_DIODE_MAX_STD_NORM`
- Hot sections must be **contiguous** (e.g. thirds [0,1] OK; [0,2] rejected)
- Coverage must be between 28 % and 72 % of panel length (i.e. 1/3 or 2/3)
- Only runs if no hot spots already dominate the same panel

#### `detect_panel_off(panel, all_panels)`
- Compute mean temperature of all other panels in the same string
- Flag if `panel.mean_temp − neighbor_mean ≤ PANEL_OFF_DELTA_CELSIUS` (threshold is negative)

---

## Defect Data Model

```python
@dataclass
class Defect:
    defect_type: str    # HOT_SPOT | BYPASS_DIODE | STRING_OFF | PANEL_OFF
    confidence:  float  # 0.0 – 1.0  (see scoring below)
    severity:    str    # LOW | MEDIUM | HIGH
    bbox:        Tuple[int, int, int, int]  # x, y, w, h  (image pixels)
    panel_bbox:  Tuple[int, int, int, int]  # enclosing panel bbox
    string_id:   int    # row index (0 = top); -1 for STRING_OFF
    panel_id:    int    # column index (0 = left); -1 for STRING_OFF
    delta_temp:  float  # anomaly magnitude in °C (negative for PANEL_OFF)
    notes:       str    # human-readable detail string
```

**Confidence scoring:**  
`confidence = min(1.0, |delta| / (|threshold| × CONFIDENCE_SATURATION_MULT))`  
- `severity = HIGH` if confidence ≥ 0.75  
- `severity = MEDIUM` if confidence ≥ 0.40  
- `severity = LOW` otherwise

---

## CSV Report Schema

One row per defect. Columns:

| Column | Type | Description |
|---|---|---|
| `project` | str | Parent directory name |
| `sequence` | str | Sequence directory name |
| `image_name` | str | Source filename |
| `defect_type` | str | `HOT_SPOT \| BYPASS_DIODE \| STRING_OFF \| PANEL_OFF` |
| `severity` | str | `LOW \| MEDIUM \| HIGH` |
| `confidence` | float | 0.0 – 1.0 |
| `string_id` | int | Row index of affected string |
| `panel_id` | int | Column index within string; -1 for STRING_OFF |
| `bbox_x` | int | Defect bounding box — left edge (px) |
| `bbox_y` | int | Defect bounding box — top edge (px) |
| `bbox_w` | int | Defect bounding box — width (px) |
| `bbox_h` | int | Defect bounding box — height (px) |
| `delta_temp_c` | float | Temperature anomaly that triggered detection (°C) |
| `notes` | str | Detailed description string |

---

## Configurable Thresholds (top of file)

All tuning constants are declared at module level. Edit these to adjust sensitivity.

### Temperature calibration

| Constant | Default | Effect |
|---|---|---|
| `THERMAL_SCALE` | `0.04` | Kelvin per raw LSB (16-bit TIFF only) |
| `THERMAL_OFFSET` | `-273.15` | K→°C offset (16-bit TIFF only) |
| `PSEUDO_COLOR_TEMP_MIN` | `15.0` | °C at pixel value 0 (8-bit images) |
| `PSEUDO_COLOR_TEMP_MAX` | `80.0` | °C at pixel value 255 (8-bit images) |

### Panel geometry

| Constant | Default | Raise when | Lower when |
|---|---|---|---|
| `MIN_PANEL_AREA` | `800` px² | Shadow blobs detected as panels | Panels appear small (high altitude) |
| `MAX_PANEL_AREA` | `100000` px² | Multi-panel blobs pass the filter | — |
| `PANEL_ASPECT_RATIO_MIN` | `0.3` | — | Portrait panels excluded |
| `PANEL_ASPECT_RATIO_MAX` | `4.0` | — | Landscape panels excluded |
| `PANEL_SOLIDITY_MIN` | `0.72` | L-shaped noise passes | Panels with visible damage cut out |

### Masking

| Constant | Default | Raise when | Lower when |
|---|---|---|---|
| `BG_PERCENTILE_LOW` | `15` | Warm ground leaks through mask | Mask cuts into real panels |
| `BG_PERCENTILE_HIGH` | `99` | Sky glint included | Hot panels incorrectly clipped |
| `MORPH_KERNEL_SIZE` | `11` px | Panel interiors not filled | Mask bleeds across panel gaps |

### Defect thresholds

| Constant | Default | Raise when | Lower when |
|---|---|---|---|
| `HOT_SPOT_DELTA_CELSIUS` | `15.0` | Too many false positives | Real hot spots missed |
| `HOT_SPOT_MIN_AREA_FRACTION` | `0.003` | Single hot pixels flagged | Small hot spots ignored |
| `HOT_SPOT_MAX_AREA_FRACTION` | `0.12` | Bypass patterns treated as hot spots | — |
| `BYPASS_DIODE_DELTA_CELSIUS` | `8.0` | Non-uniform warm zones flagged | Real bypass failures missed |
| `BYPASS_DIODE_MAX_STD_NORM` | `0.08` | Gradient zones treated as bypass | Only perfectly uniform sections flagged |
| `STRING_OFF_DELTA_CELSIUS` | `12.0` | Strings flagged on minor variation | Real string faults missed |
| `STRING_GROUP_TOLERANCE` | `0.08` | Same-string panels split into two rows | Adjacent-string panels merged |
| `PANEL_OFF_DELTA_CELSIUS` | `-10.0` | Cold panels on shaded edge flagged | Genuinely off panels missed |

---

## Annotation Colors (BGR)

| Defect | Color |
|---|---|
| `HOT_SPOT` | Red `(0, 0, 255)` |
| `BYPASS_DIODE` | Orange `(0, 140, 255)` |
| `STRING_OFF` | Yellow `(0, 215, 255)` |
| `PANEL_OFF` | Teal-blue `(255, 180, 0)` |

All healthy panels are outlined in dark green with their `S<id>P<id>` label.  
A semi-transparent legend is drawn in the top-right corner of every annotated image.

---

## Key Functions — Quick Reference

| Function | Signature | Returns |
|---|---|---|
| `load_thermal_image` | `(path) → (gray_u8, temp_map_f32)` | Calibrated temperature map |
| `load_bgr` | `(path, gray_fallback) → ndarray` | BGR image for annotation |
| `create_panel_mask` | `(temp_map) → mask_u8` | Binary panel mask |
| `segment_panels` | `(mask, temp_map) → List[Panel]` | Panels with string/panel IDs |
| `run_all_detectors` | `(panels, temp_map) → List[Defect]` | All detected defects |
| `annotate` | `(color_img, panels, defects) → ndarray` | Annotated BGR image |
| `append_csv` | `(report_path, rows)` | Appends to CSV (creates header if new) |
| `process_image` | `(img_path, out_dir, report_path, project, seq) → int` | Defect count |
| `process_sequence` | `(seq_dir, out_root, report_path, project) → (n_imgs, n_defs)` | Totals |
| `process_project` | `(proj_dir, out_root, report_path)` | Iterates all sequences |

---

## Dependencies

All already present in `requirements.txt`:

```
opencv-python-headless
numpy
scipy  (imported as optional; not strictly required for current detectors)
```

---

## Known Limitations and Caveats

- **Temperature accuracy** depends on correct `THERMAL_SCALE` / `THERMAL_OFFSET` for your specific camera. Wrong calibration degrades °C-based thresholds.
- **8-bit pseudo-color accuracy** is approximate — the red-channel proxy is monotonic but not linear in all palettes. For precise °C values, always supply 16-bit radiometric TIFFs.
- **Panel segmentation** assumes panels form horizontal rows and a roughly nadir (top-down) camera angle. Oblique angles or highly tilted racks may confuse string grouping.
- **STRING_OFF** requires at least two distinct strings in the image to make a comparison.
- **Overlapping defects** — a panel flagged as `STRING_OFF` is excluded from per-panel checks. Remove the `string_off_ids` guard in `run_all_detectors` if both levels of detail are needed simultaneously.
- **No deep learning** — the segmentation is contour-based. Dense vegetation encroachment, heavy soiling, or unusual panel geometries may degrade mask quality. YOLOv8 weights (`yolov8m.pt`) present in this repo can be integrated as an optional upgrade path for segmentation.
