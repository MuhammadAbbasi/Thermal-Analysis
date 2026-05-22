"""
Stage 2 — Layout ingestion and spatial matching.

Supports:
  - GeoJSON FeatureCollection (Point or Polygon features)
  - CSV with columns: panel_id, latitude, longitude

For each defect coordinate, matches to the nearest panel via:
  1. Point-in-polygon test (Shapely) — exact hit
  2. Nearest centroid fallback (KDTree) — when no polygon contains the point
"""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from shapely.geometry import Point, shape
from scipy.spatial import KDTree


@dataclass
class PanelEntry:
    panel_id: str
    centroid_lat: float
    centroid_lon: float
    geometry: object = None  # shapely geometry, or None for point-only entries


_ID_FIELDS  = ["panel_id", "PanelID", "PANEL_ID", "id", "ID", "name", "Name", "label", "Label", "fid", "FID"]
_LAT_FIELDS = ["latitude", "lat", "Latitude", "LAT", "y", "Y"]
_LON_FIELDS = ["longitude", "lon", "lng", "Longitude", "LON", "LNG", "x", "X"]


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres between two WGS84 points."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


class LayoutStore:
    """Holds parsed panel geometries and provides spatial matching."""

    def __init__(self):
        self.panels: List[PanelEntry] = []
        self._kdtree: Optional[KDTree] = None
        self._cos_lat: float = 1.0

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def load_geojson(self, content: str | bytes) -> int:
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        data = json.loads(content)
        features = data.get("features", []) if data.get("type") == "FeatureCollection" else [data]

        for feat in features:
            props = feat.get("properties") or {}
            geom_data = feat.get("geometry")
            if not geom_data:
                continue

            panel_id = next(
                (str(props[f]) for f in _ID_FIELDS if f in props and props[f] is not None),
                f"PANEL-{len(self.panels) + 1:04d}",
            )

            try:
                geom = shape(geom_data)
                centroid = geom.centroid
                self.panels.append(PanelEntry(
                    panel_id=panel_id,
                    centroid_lat=centroid.y,
                    centroid_lon=centroid.x,
                    geometry=geom,
                ))
            except Exception:
                continue

        self._rebuild_index()
        return len(self.panels)

    def load_csv(self, content: str | bytes) -> int:
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))

        for row in reader:
            lat = next(
                (float(row[f]) for f in _LAT_FIELDS if f in row and row[f]),
                None,
            )
            lon = next(
                (float(row[f]) for f in _LON_FIELDS if f in row and row[f]),
                None,
            )
            if lat is None or lon is None:
                continue
            pid = next(
                (str(row[f]) for f in _ID_FIELDS if f in row and row[f]),
                f"PANEL-{len(self.panels) + 1:04d}",
            )
            self.panels.append(PanelEntry(panel_id=pid, centroid_lat=lat, centroid_lon=lon))

        self._rebuild_index()
        return len(self.panels)

    # ------------------------------------------------------------------
    # Spatial index
    # ------------------------------------------------------------------

    def _rebuild_index(self):
        if not self.panels:
            self._kdtree = None
            return
        lat0 = np.mean([p.centroid_lat for p in self.panels])
        self._cos_lat = math.cos(math.radians(lat0))
        coords = np.array([
            [p.centroid_lat * 111_320.0, p.centroid_lon * 111_320.0 * self._cos_lat]
            for p in self.panels
        ])
        self._kdtree = KDTree(coords)

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match(self, lat: float, lon: float) -> Tuple[str, float]:
        """Return (panel_id, distance_m) for the best matching panel."""
        if not self.panels:
            return "UNMATCHED", -1.0

        pt = Point(lon, lat)  # shapely: (x=lon, y=lat)

        # 1. Point-in-polygon
        for panel in self.panels:
            if panel.geometry is not None:
                try:
                    if panel.geometry.contains(pt):
                        dist = _haversine_m(lat, lon, panel.centroid_lat, panel.centroid_lon)
                        return panel.panel_id, round(dist, 3)
                except Exception:
                    pass

        # 2. Nearest centroid
        if self._kdtree is None:
            return self.panels[0].panel_id, 0.0

        query = np.array([lat * 111_320.0, lon * 111_320.0 * self._cos_lat])
        _, idx = self._kdtree.query(query)
        panel = self.panels[int(idx)]
        dist = _haversine_m(lat, lon, panel.centroid_lat, panel.centroid_lon)
        return panel.panel_id, round(dist, 3)
