"""Project classified source tags into typed assertions and media fields."""

from __future__ import annotations

from gamedb.derive.parser.classifier import ClassifiedTags

from ..models import Assertion, InterpretedTag, MediaPart


class TagExtractor:
    """Convert classifier output into relational values once, in Python."""

    CODE_CATEGORIES = frozenset({
        "release_status", "demo", "copyright_status", "license", "special",
        "distribution_channel", "dump_modification", "dump_status",
    })
    TEXT_CATEGORIES = frozenset({
        "version", "revision", "release_date", "publisher",
        "system_requirement", "video", "media_label",
    })

    def extract(self, raw_tags: list[dict], classified: ClassifiedTags):
        tags = []
        assertions = []
        media_parts = []
        for index, (raw, meaning) in enumerate(
            zip(raw_tags, classified.tags), 1
        ):
            tag = InterpretedTag(
                index=index,
                raw_value=raw["value"],
                delimiter=raw["delimiter"],
                source_start=raw["start"],
                source_end=raw["end"],
                identifier=meaning["identifier"],
                value=meaning["value"],
                category=meaning["category"],
                classification_status=meaning["status"],
                rule=meaning["rule"],
                details=meaning["details"],
            )
            tags.append(tag)
            if meaning["status"] != "classified":
                continue
            assertions.extend(self._assertions(index, meaning))
            media = self._media(index, meaning)
            if media is not None:
                media_parts.append(media)
        return tuple(tags), tuple(assertions), tuple(media_parts)

    def _assertions(self, index: int, meaning: dict) -> list[Assertion]:
        category = meaning["category"]
        details = meaning["details"]
        values: list[tuple[str, object]] = []
        if category in ("region", "language"):
            values.extend((category, value) for value in details.get("codes", []))
        if category == "dump_modification" and details.get("code") == "translated":
            values.extend(
                ("language", value)
                for value in details.get("language_codes", [])
            )
            if details.get("version"):
                values.append(("version", details["version"]))
            if details.get("revision"):
                values.append(("revision", details["revision"]))
            values.extend(
                ("dump_modification", value)
                for value in details.get("additional_modifications", [])
            )
        if category in self.CODE_CATEGORIES and details.get("code"):
            values.append((category, details["code"]))
        if category in self.TEXT_CATEGORIES and details.get("text"):
            values.append((category, details["text"]))
        if category == "language" and "count" in details:
            values.append(("language_count", details["count"]))
        if category == "bios":
            values.append(("bios", "true"))
        if category in ("region", "publisher") and details.get("unknown"):
            values.append((category, "unknown"))
        return [
            Assertion(key, str(value), index)
            for key, value in values
            if str(value).strip()
        ]

    @staticmethod
    def _media(index: int, meaning: dict) -> MediaPart | None:
        if meaning["category"] != "media":
            return None
        details = meaning["details"]
        part = details.get("part")
        return MediaPart(
            source_tag_index=index,
            media_type=details["type"],
            part=part,
            sequence=int(part) if isinstance(part, str) and part.isdigit() and int(part) > 0 else None,
            total=details.get("total"),
            total_label=details.get("total_label"),
            side=details.get("side"),
            label=details.get("label"),
            description=details.get("description"),
        )
