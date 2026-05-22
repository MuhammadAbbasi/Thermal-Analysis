"""
Pixel-to-GPS ray-tracer.

Converts a bounding-box center pixel in a drone image to a real-world
GPS coordinate using the drone's altitude, gimbal pitch, flight yaw,
and camera intrinsics.

Coordinate frames
-----------------
Camera  : x = image-right, y = image-down, z = into scene (OpenCV/image convention)
World   : ENU — East, North, Up
DJI yaw : 0° = North, 90° = East (clockwise from north)
DJI pitch: 0° = horizontal-forward, -90° = nadir (straight down)
"""
from __future__ import annotations
import math
from typing import Tuple

import numpy as np

from app.exif_parser import FrameMeta


def _build_cam_to_enu(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    """
    Return 3×3 rotation matrix R mapping camera-frame vectors to world ENU.

    At nadir (pitch = -90°) with yaw = 0° (north):
      cam-x (right)      → world East
      cam-y (image-down) → world South = −North
      cam-z (into scene) → world Down  = −Up
    """
    # phi: tilt from nadir toward drone-forward direction  (0 = nadir, 90 = horizontal)
    phi = math.radians(90.0 + pitch_deg)
    theta = math.radians(yaw_deg)           # clockwise from north

    cp, sp = math.cos(phi), math.sin(phi)
    ct, st = math.cos(theta), math.sin(theta)

    # Drone axes in ENU
    drone_right   = np.array([ ct, -st, 0.0])   # cam-x at any phi
    drone_forward = np.array([ st,  ct, 0.0])   # nose direction
    world_up      = np.array([0.0, 0.0, 1.0])

    cam_x = drone_right
    cam_y = -cp * drone_forward - sp * world_up   # image-down axis
    cam_z =  sp * drone_forward - cp * world_up   # into-scene axis

    # Columns of R: where each camera axis points in ENU
    R = np.column_stack([cam_x, cam_y, cam_z])    # shape (3, 3)
    return R


def pixel_to_gps(
    px: float,
    py: float,
    meta: FrameMeta,
) -> Tuple[float, float]:
    """
    Ray-trace the pixel (px, py) to GPS (lat, lon).

    Returns the drone's GPS if altitude is zero or the ray never hits
    the ground plane.
    """
    if meta.altitude_m <= 0:
        return meta.latitude, meta.longitude

    # Focal length in pixels
    f_px = meta.focal_mm * meta.image_w / meta.sensor_w_mm

    # Offset from principal point (image centre)
    u = px - meta.image_w / 2.0
    v = py - meta.image_h / 2.0

    # Ray in camera frame (un-normalised, z-component = 1)
    ray_cam = np.array([u / f_px, v / f_px, 1.0])

    # Rotate to world ENU
    R = _build_cam_to_enu(meta.flight_yaw_deg, meta.gimbal_pitch_deg)
    ray_enu = R @ ray_cam   # [east, north, up] components

    # Intersect with ground plane (z = 0).
    # Camera sits at (0, 0, H) in local ENU; ground at z = 0.
    # Point on ray: (0, 0, H) + t * ray_enu  →  z = 0  →  t = -H / ray_enu[2]
    if ray_enu[2] >= 0.0:
        # Ray points upward — no ground intersection; return drone position
        return meta.latitude, meta.longitude

    t = -meta.altitude_m / ray_enu[2]   # t > 0

    east_m  = ray_enu[0] * t
    north_m = ray_enu[1] * t

    # Convert metre offsets to degree offsets
    lat0_rad = math.radians(meta.latitude)
    delta_lat = north_m / 111_320.0
    delta_lon = east_m  / (111_320.0 * math.cos(lat0_rad))

    return meta.latitude + delta_lat, meta.longitude + delta_lon


def compute_gsd(meta: FrameMeta) -> float:
    """Return Ground Sample Distance in metres/pixel (horizontal)."""
    if meta.focal_mm == 0:
        return 0.0
    return meta.altitude_m * meta.sensor_w_mm / (meta.focal_mm * meta.image_w)
