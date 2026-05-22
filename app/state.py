"""Shared in-memory state — imported by both main.py and plant_router.py."""
from __future__ import annotations
from typing import Dict, Optional

from app.models import ScanResponse
from app.layout_mapper import LayoutStore

scan_store: Dict[str, ScanResponse] = {}
layout_store: Optional[LayoutStore] = None
