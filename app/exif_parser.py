"""
EXIF + XMP parser for DJI thermal JPEG images.
Extracts GPS, altitude, gimbal angles, focal length from both standard EXIF
and DJI-specific XMP metadata blocks.
"""
from __future__ import annotations
import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS


@dataclass
class FrameMeta:
    path: str
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_m: float = 25.0          # RelativeAltitude
    gimbal_pitch_deg: float = -90.0   # -90 = nadir
    gimbal_yaw_deg: float = 0.0
    flight_yaw_deg: float = 0.0
    focal_mm: float = 13.0
    sensor_w_mm: float = 10.88
    sensor_h_mm: float = 8.71
    image_w: int = 640
    image_h: int = 512
    camera_model: str = "DEFAULT"
    valid_gps: bool = False


def _dms_to_decimal(dms, ref: str) -> float:
    """Convert (degrees, minutes, seconds) tuple + hemisphere ref to decimal degrees."""
    try:
        d = float(dms[0])
        m = float(dms[1])
        s = float(dms[2])
        dec = d + m / 60.0 + s / 3600.0
        if ref in ("S", "W"):
            dec = -dec
        return dec
    except Exception:
        return 0.0


def _parse_standard_exif(img: Image.Image) -> dict:
    """Return dict of decoded EXIF tags."""
    try:
        raw = img._getexif()
    except Exception:
        raw = None
    if not raw:
        return {}
    out: dict = {}
    for tag_id, val in raw.items():
        tag = TAGS.get(tag_id, str(tag_id))
        out[tag] = val
    return out


def _parse_gps_from_exif(exif: dict) -> tuple[Optional[float], Optional[float]]:
    """Extract lat/lon from PIL EXIF GPSInfo block."""
    gps_info = exif.get("GPSInfo")
    if not gps_info:
        return None, None
    gps: dict = {}
    for key, val in gps_info.items():
        name = GPSTAGS.get(key, str(key))
        gps[name] = val
    lat = gps.get("GPSLatitude")
    lat_ref = gps.get("GPSLatitudeRef", "N")
    lon = gps.get("GPSLongitude")
    lon_ref = gps.get("GPSLongitudeRef", "E")
    if lat and lon:
        return _dms_to_decimal(lat, lat_ref), _dms_to_decimal(lon, lon_ref)
    return None, None


def _extract_xmp_block(path: str) -> str:
    """Read raw JPEG bytes and extract the XMP XML block."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        start = data.find(b"<x:xmpmeta")
        if start == -1:
            start = data.find(b"<?xpacket")
        end = data.find(b"</x:xmpmeta>")
        if start != -1 and end != -1:
            return data[start : end + len(b"</x:xmpmeta>")].decode("utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def _xmp_attr(xmp: str, attr: str) -> Optional[str]:
    """Extract a single attribute value from XMP string by regex."""
    pattern = rf'{re.escape(attr)}="([^"]+)"'
    m = re.search(pattern, xmp)
    if m:
        return m.group(1)
    # Also try element form: <attr>value</attr>
    pattern2 = rf'<{re.escape(attr)}>([^<]+)</{re.escape(attr)}>'
    m2 = re.search(pattern2, xmp)
    if m2:
        return m2.group(1)
    return None


_SENSOR_LOOKUP = {
    "XT2":  (13.0, 10.88, 8.71),
    "XT":   (9.0,  10.88, 8.71),
    "H20T": (13.5,  8.64, 6.93),
    "M2EA": (8.8,   7.68, 4.32),  # Mavic 2 Enterprise Advanced
}


def _sensor_from_model(model_str: str) -> tuple[float, float, float]:
    """Return (focal_mm, sensor_w_mm, sensor_h_mm) for a known camera model string."""
    m = model_str.upper()
    for key, vals in _SENSOR_LOOKUP.items():
        if key in m:
            return vals
    return (13.0, 10.88, 8.71)  # default DJI thermal


def parse_frame(path: str) -> FrameMeta:
    """Parse all available metadata from a DJI thermal JPEG."""
    meta = FrameMeta(path=path)

    try:
        img = Image.open(path)
        meta.image_w, meta.image_h = img.size
        exif = _parse_standard_exif(img)
    except Exception:
        exif = {}

    # --- Camera model → sensor specs ---
    model_str = str(exif.get("Model", ""))
    meta.camera_model = model_str or "DEFAULT"
    focal_exif = exif.get("FocalLength")
    f_mm, sw_mm, sh_mm = _sensor_from_model(model_str)
    if focal_exif:
        try:
            f_mm = float(focal_exif)
        except Exception:
            pass
    meta.focal_mm = f_mm
    meta.sensor_w_mm = sw_mm
    meta.sensor_h_mm = sh_mm

    # --- GPS from standard EXIF ---
    lat, lon = _parse_gps_from_exif(exif)

    # --- Altitude from standard EXIF ---
    alt_raw = exif.get("GPSAltitude")
    if alt_raw:
        try:
            meta.altitude_m = float(alt_raw)
        except Exception:
            pass

    # --- XMP block (DJI-specific fields) ---
    xmp = _extract_xmp_block(path)
    if xmp:
        def xf(attr):
            return _xmp_attr(xmp, attr)

        # GPS (XMP may override standard EXIF)
        xmp_lat = xf("drone-dji:GpsLatitude") or xf("Camera:GPSLatitude")
        xmp_lon = xf("drone-dji:GpsLongitude") or xf("Camera:GPSLongitude")
        if xmp_lat:
            try:
                lat = float(xmp_lat)
            except Exception:
                pass
        if xmp_lon:
            try:
                lon = float(xmp_lon)
            except Exception:
                pass

        # Relative altitude (above takeoff point — more reliable than GPS altitude)
        rel_alt = xf("drone-dji:RelativeAltitude") or xf("Camera:RelativeAltitude")
        if rel_alt:
            try:
                meta.altitude_m = float(rel_alt.lstrip("+"))
            except Exception:
                pass

        # Gimbal angles
        pitch = xf("drone-dji:GimbalPitchDegree") or xf("Camera:Pitch")
        yaw   = xf("drone-dji:GimbalYawDegree")   or xf("Camera:Yaw")
        flight_yaw = xf("drone-dji:FlightYawDegree")
        if pitch:
            try:
                meta.gimbal_pitch_deg = float(pitch)
            except Exception:
                pass
        if yaw:
            try:
                meta.gimbal_yaw_deg = float(yaw)
            except Exception:
                pass
        if flight_yaw:
            try:
                meta.flight_yaw_deg = float(flight_yaw)
            except Exception:
                pass
        else:
            meta.flight_yaw_deg = meta.gimbal_yaw_deg

        # Focal length from XMP
        fc = xf("drone-dji:CalibratedFocalLength") or xf("Camera:FocalLength")
        if fc:
            try:
                # May be in pixels → convert to mm: f_mm = f_px * sensor_w_mm / image_w
                v = float(fc)
                if v > 100:  # likely in pixels
                    meta.focal_mm = v * meta.sensor_w_mm / max(meta.image_w, 1)
                else:
                    meta.focal_mm = v
            except Exception:
                pass

    if lat is not None and lon is not None and (lat != 0.0 or lon != 0.0):
        meta.latitude = lat
        meta.longitude = lon
        meta.valid_gps = True

    return meta
