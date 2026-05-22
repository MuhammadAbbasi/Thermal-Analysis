import os

# DJI thermal camera sensor specs (focal_mm, sensor_w_mm, sensor_h_mm)
SENSOR_SPECS = {
    "ZENMUSE XT2":  {"focal_mm": 13.0, "sensor_w_mm": 10.88, "sensor_h_mm": 8.71},
    "ZENMUSE H20T": {"focal_mm": 13.5, "sensor_w_mm":  8.64, "sensor_h_mm": 6.93},
    "ZENMUSE XT":   {"focal_mm": 9.0,  "sensor_w_mm": 10.88, "sensor_h_mm": 8.71},
    "DEFAULT":      {"focal_mm": 13.0, "sensor_w_mm": 10.88, "sensor_h_mm": 8.71},
}

CLASS_NAMES = {
    0: "hotspot",
    1: "bypass_diode",
    2: "hot_region",
    3: "cold_region",
}

WEIGHTS_DIR = os.path.join(os.path.dirname(__file__), "..", "weights")
os.makedirs(WEIGHTS_DIR, exist_ok=True)
_custom_weights = os.path.join(WEIGHTS_DIR, "yolov8m.pt")
# Fall back to ultralytics auto-download if no custom weights are present
MODEL_WEIGHTS = _custom_weights if os.path.exists(_custom_weights) else "yolov8m.pt"

CONF_THRESHOLD = 0.25
IOU_THRESHOLD  = 0.45
MIN_FRAMES_TRACKED = 2  # min frames a track must appear to be logged as a defect

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")
