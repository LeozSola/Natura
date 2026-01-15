"""
Natura core package.

This package centralises reusable utilities shared across the scenic routing
pipeline. The initial focus is on providing a lightweight caching layer,
geo-processing helpers, and heatmap generation that other scripts can import.
"""

from .cache import DiskCache  # noqa: F401
