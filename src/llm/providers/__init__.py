"""Vision provider adapters.

Each adapter implements the VisionProvider interface defined in base.py.
Provider selection is controlled by the VISION_PROVIDER environment variable.
"""

from .base import VisionProvider

__all__ = ["VisionProvider"]
