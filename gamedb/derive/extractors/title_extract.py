"""Create a stable grouping signature for one parsed source title record."""

from __future__ import annotations

import hashlib
import json

from ..models import InterpretedTag


class TitleExtractor:
    """Retain the source title and fingerprint its non-media interpretation."""

    @staticmethod
    def grouping_signature(tags: tuple[InterpretedTag, ...]) -> str:
        payload = [
            {
                "index": tag.index,
                "raw": tag.raw_value,
                "identifier": tag.identifier,
                "value": tag.value,
                "category": tag.category,
                "status": tag.classification_status,
                "details": tag.details,
            }
            for tag in tags
            if tag.category != "media"
        ]
        serialized = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
