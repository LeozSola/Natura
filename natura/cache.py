"""
Lightweight disk cache utilities.

The scenic routing pipeline repeatedly calls external services (Overpass,
Mapillary, OSRM). To avoid downloading the same payload multiple times we keep
simple on-disk caches keyed by a deterministic string (typically a hashed JSON
representation of the request parameters).

The cache intentionally keeps the implementation minimal so the existing scripts
can adopt it without introducing third-party dependencies such as
``requests-cache``.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


CacheFactory = Callable[[], Any]


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _serialise(value: Any) -> str:
    return json.dumps(
        {
            "created": time.time(),
            "payload": value,
        },
        ensure_ascii=False,
    )


def _deserialise(raw: str) -> Any:
    data = json.loads(raw)
    if isinstance(data, dict) and "payload" in data:
        return data["payload"], float(data.get("created", 0.0))
    return data, 0.0


@dataclass
class DiskCache:
    """A very small helper around directory-based JSON caching."""

    root: Path
    namespace: str = "default"
    max_age: Optional[float] = None  # seconds; None means no expiry

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.cache_dir = self.root / self.namespace
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _hash_key(self, key: str) -> str:
        return hashlib.sha1(key.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{self._hash_key(key)}.json"

    @staticmethod
    def key_from_mapping(mapping: Any) -> str:
        """Build a deterministic key from a JSON-serialisable mapping."""
        return json.dumps(mapping, sort_keys=True, separators=(",", ":"))

    def load(self, key: str) -> Optional[Any]:
        path = self._path(key)
        if not path.exists():
            return None
        if self.max_age is not None:
            age = time.time() - path.stat().st_mtime
            if age > self.max_age:
                try:
                    path.unlink()
                except OSError:
                    pass
                return None
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        payload, _created = _deserialise(raw)
        return payload

    def save(self, key: str, value: Any) -> None:
        path = self._path(key)
        _ensure_dir(path)
        payload = _serialise(value)
        path.write_text(payload, encoding="utf-8")

    def get_or_create(self, key: str, factory: CacheFactory) -> Any:
        cached = self.load(key)
        if cached is not None:
            return cached
        value = factory()
        self.save(key, value)
        return value

