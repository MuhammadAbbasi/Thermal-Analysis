"""Verify that thermal image GPS coordinates match plant layout WGS84 extent."""
import os, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = os.path.dirname(os.path.abspath(__file__))

# 1. Sample first 5 images from data folder
img_dir = os.path.join(BASE, "data", "SP3", "2026_05_13")
if not os.path.exists(img_dir):
    print(f"Image dir not found: {img_dir}")
else:
    from app.exif_parser import parse_frame
    from pathlib import Path
    jpgs = sorted(Path(img_dir).glob("*.JPG"))[:5]
    print("=== Thermal image GPS (from EXIF) ===")
    for p in jpgs:
        m = parse_frame(str(p))
        print(f"  {p.name}  lat={m.latitude:.6f}  lon={m.longitude:.6f}  alt={m.altitude_m:.1f}m  valid_gps={m.valid_gps}")

# 2. Plant layout bounds
meta_path = os.path.join(BASE, "data", "plant_metadata.json")
if os.path.exists(meta_path):
    meta = json.load(open(meta_path))
    b = meta.get("wgs84_bounds", {})
    c = meta.get("plant_centroid", {})
    print("\n=== Plant layout bounds (WGS84) ===")
    print(f"  Lat: {b.get('lat_min'):.6f} – {b.get('lat_max'):.6f}")
    print(f"  Lon: {b.get('lon_min'):.6f} – {b.get('lon_max'):.6f}")
    print(f"  Centroid: {c.get('lat'):.6f}N, {c.get('lon'):.6f}E")
