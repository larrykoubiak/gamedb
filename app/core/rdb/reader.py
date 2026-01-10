"""Minimal class-based API for RetroArch .rdb files.

`Rdb` encapsulates parsing and serialization of the .rdb binary format and
offers a `to_dataframe()` helper (pandas optional) for downstream analysis.
"""

from __future__ import annotations

import binascii
import struct
from collections import OrderedDict, namedtuple
from typing import Any, Dict, List, Optional


# MessagePack markers used by RetroArch .rdb files
MPF_FIXMAP = 0x80
MPF_MAP16 = 0xde
MPF_MAP32 = 0xdf

MPF_FIXARRAY = 0x90
MPF_ARRAY16 = 0xdc
MPF_ARRAY32 = 0xdd

MPF_FIXSTR = 0xa0
MPF_STR8 = 0xd9
MPF_STR16 = 0xda
MPF_STR32 = 0xdb

MPF_BIN8 = 0xc4
MPF_BIN16 = 0xc5
MPF_BIN32 = 0xc6

MPF_FALSE = 0xc2
MPF_TRUE = 0xc3

MPF_INT8 = 0xd0
MPF_INT16 = 0xd1
MPF_INT32 = 0xd2
MPF_INT64 = 0xd3

MPF_UINT8 = 0xcc
MPF_UINT16 = 0xcd
MPF_UINT32 = 0xce
MPF_UINT64 = 0xcf

MPF_NIL = 0xc0


rdbheader = namedtuple("rdbheader", "magic_number metadata_offset")
rmsg = namedtuple("rmsg", "typ value")
rfield = namedtuple("rdbfield", "name value type")


class Rdb:
    """Single entry point for reading/writing RetroArch .rdb files."""

    def __init__(
        self,
        columns: Optional[OrderedDict[str, str]] = None,
        rows: Optional[List[OrderedDict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        header: Optional[rdbheader] = None,
        path: Optional[str] = None,
    ):
        self.columns: OrderedDict[str, str] = columns or OrderedDict()
        self.rows: List[OrderedDict[str, Any]] = rows or []
        self.metadata: Dict[str, Any] = metadata or {}
        self.header: rdbheader = header or rdbheader(b"RARCHDB\0", 0)
        self.path: Optional[str] = path

    # -- public API ---------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "Rdb":
        with open(path, "rb") as handle:
            data = bytearray(handle.read())
        return cls.from_bytes(data, path)

    @classmethod
    def from_bytes(cls, data: bytearray, path: Optional[str] = None) -> "Rdb":
        if len(data) < 16:
            raise ValueError("RDB file too small to contain a valid header.")

        header = rdbheader._make(struct.unpack("8sQ", data[:16]))
        index = 16
        columns: OrderedDict[str, str] = OrderedDict()
        rows: List[OrderedDict[str, Any]] = []
        metadata: Dict[str, Any] = {}

        while index < len(data):
            index, msg = cls._get_rmsg(data, index)
            if msg.typ != "fixmap":
                continue

            record = OrderedDict()
            field_types: Dict[str, str] = {}
            for _ in range(msg.value):
                index, fld = cls._read_rfield(data, index)
                record[fld.name] = fld.value
                field_types[fld.name] = fld.type

            if len(record) == 1 and "count" in record:
                metadata["count"] = record["count"]
                continue

            for name, typ in field_types.items():
                columns.setdefault(name, typ)
            rows.append(record)

        if "name" in columns:
            rows.sort(key=lambda row: row.get("name", ""))

        metadata.setdefault("count", len(rows))
        return cls(columns=columns, rows=rows, metadata=metadata, header=header, path=path)

    def save(self, path: Optional[str] = None) -> str:
        target = path or self.path
        if not target:
            raise ValueError("No output path provided; pass `path` or set `table.path`.")
        data = self.to_bytes()
        with open(target, "wb") as handle:
            handle.write(data)
        self.path = target
        return target

    def to_bytes(self) -> bytearray:
        buffer = bytearray()
        buffer += struct.pack("8sQ", *self.header)

        for record in self.rows:
            buffer += self._set_rmsg(rmsg("fixmap", len(record)))
            for key, value in record.items():
                value_type = self.columns.get(key, self._infer_field_type(value))
                buffer += self._write_rfield(key, value, value_type)

        buffer += self._set_rmsg(rmsg("nil", None))
        buffer += self._set_rmsg(rmsg("fixmap", 1))
        buffer += self._write_rfield("count", len(self.rows), "uint")
        return buffer

    def to_dataframe(self, sort_by: Optional[str] = "name"):
        """Return the data as a pandas DataFrame."""
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            raise ImportError("pandas is required for to_dataframe()") from exc

        df = pd.DataFrame(self.rows)
        if sort_by and sort_by in df.columns:
            df = df.sort_values(sort_by).reset_index(drop=True)
        return df

    def as_legacy_mapping(self) -> Dict[str, Any]:
        """Return a dict compatible with the previous API."""
        return {
            "columns": self.columns.copy(),
            "rows": list(self.rows),
            "metadata": dict(self.metadata),
        }

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _infer_field_type(value: Any) -> str:
        if value is None:
            return "nil"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "uint" if value >= 0 else "int"
        if isinstance(value, (bytes, bytearray)):
            return "binstr"
        return "string"

    @staticmethod
    def _read_rfield(data: bytearray, offset: int) -> tuple[int, rfield]:
        index, namemsg = Rdb._get_rmsg(data, offset)
        index, valuemsg = Rdb._get_rmsg(data, index)
        name = Rdb._normalize_key(namemsg.value)
        return index, rfield(name, valuemsg.value, valuemsg.typ)

    @staticmethod
    def _write_rfield(name: str, value: Any, field_type: str) -> bytearray:
        payload = bytearray()
        payload += Rdb._set_rmsg(rmsg("string", name))
        payload += Rdb._set_rmsg(rmsg(field_type, value))
        return payload

    @staticmethod
    def _get_rmsg(data: bytearray, index: int) -> tuple[int, rmsg]:
        buf = data[index]

        if buf <= 0x7F:
            return index + 1, rmsg("int", buf)
        if buf >= 0xE0:
            return index + 1, rmsg("int", struct.unpack("b", bytes([buf]))[0])
        if MPF_FIXMAP <= buf <= 0x8F:
            return index + 1, rmsg("fixmap", buf & 0x0F)
        if MPF_FIXARRAY <= buf <= 0x9F:
            msglen = buf & 0x0F
            return index + msglen + 1, rmsg("fixarray", data[index + 1: index + 1 + msglen])
        if MPF_FIXSTR <= buf <= 0xBF:
            msglen = buf & 0x1F
            return (
                index + msglen + 1,
                rmsg("string", data[index + 1: index + 1 + msglen].decode("utf-8", errors="replace")),
            )

        if buf == MPF_NIL:
            return index + 1, rmsg("nil", None)
        if buf == MPF_FALSE:
            return index + 1, rmsg("bool", False)
        if buf == MPF_TRUE:
            return index + 1, rmsg("bool", True)

        if buf == MPF_BIN8 or buf == MPF_BIN16 or buf == MPF_BIN32:
            bytelen = (buf ^ MPF_BIN8) + 1
            unpackformat = str(bytelen) + "B"
            msglen = struct.unpack(unpackformat, data[index + 1: index + bytelen + 1])[0]
            val = binascii.hexlify(data[index + bytelen + 1: index + bytelen + msglen + 1])
            return index + msglen + bytelen + 1, rmsg("binstr", val.decode("ascii"))

        if buf == MPF_UINT8:
            return index + 2, rmsg("uint", struct.unpack(">B", data[index + 1: index + 2])[0])
        if buf == MPF_UINT16:
            return index + 3, rmsg("uint", struct.unpack(">H", data[index + 1: index + 3])[0])
        if buf == MPF_UINT32:
            return index + 5, rmsg("uint", struct.unpack(">I", data[index + 1: index + 5])[0])
        if buf == MPF_UINT64:
            return index + 9, rmsg("uint", struct.unpack(">Q", data[index + 1: index + 9])[0])

        if buf == MPF_INT8:
            return index + 2, rmsg("int", struct.unpack(">b", data[index + 1: index + 2])[0])
        if buf == MPF_INT16:
            return index + 3, rmsg("int", struct.unpack(">h", data[index + 1: index + 3])[0])
        if buf == MPF_INT32:
            return index + 5, rmsg("int", struct.unpack(">i", data[index + 1: index + 5])[0])
        if buf == MPF_INT64:
            return index + 9, rmsg("int", struct.unpack(">q", data[index + 1: index + 9])[0])

        if buf == MPF_STR8 or buf == MPF_STR16 or buf == MPF_STR32:
            bytelen = (buf ^ MPF_STR8) + 1
            unpackformat = str(bytelen) + "B"
            msglen = struct.unpack(unpackformat, data[index + 1: index + bytelen + 1])[0]
            val = data[index + bytelen + 1: index + bytelen + msglen + 1].decode(
                "utf-8", errors="replace"
            )
            return index + msglen + bytelen + 1, rmsg("string", val)
        if buf == MPF_MAP16:
            val = struct.unpack(">H", data[index + 1: index + 3])[0]
            return index + 3, rmsg("fixmap", val)
        if buf == MPF_MAP32:
            val = struct.unpack(">I", data[index + 1: index + 5])[0]
            return index + 5, rmsg("fixmap", val)

        raise ValueError(f"Unknown MessagePack prefix: {hex(buf)} at offset {index}")

    @staticmethod
    def _set_rmsg(message: rmsg) -> bytearray:
        if message.typ == "fixmap":
            if message.value < (1 << 4):
                return bytearray(struct.pack("B", MPF_FIXMAP | message.value))
            if message.value < (1 << 16):
                return bytearray(struct.pack(">BH", MPF_MAP16, message.value))
            if message.value < (1 << 32):
                return bytearray(struct.pack(">BI", MPF_MAP32, message.value))
        elif message.typ == "string":
            strlen = len(message.value)
            encoded = message.value.encode("utf-8")
            if strlen < (1 << 5):
                return bytearray(struct.pack(f"B{strlen}s", MPF_FIXSTR | strlen, encoded))
            if strlen < (1 << 8):
                return bytearray(struct.pack(f">BB{strlen}s", MPF_STR8, strlen, encoded))
            if strlen < (1 << 16):
                return bytearray(struct.pack(f">BH{strlen}s", MPF_STR16, strlen, encoded))
            return bytearray(struct.pack(f">BI{strlen}s", MPF_STR32, strlen, encoded))
        elif message.typ == "binstr":
            binstr = bytearray(binascii.unhexlify(message.value))
            strlen = len(binstr)
            if strlen < (1 << 8):
                return bytearray(struct.pack(f">BB{strlen}B", MPF_BIN8, strlen, *binstr))
            if strlen < (1 << 16):
                return bytearray(struct.pack(f">BH{strlen}B", MPF_BIN16, strlen, *binstr))
            return bytearray(struct.pack(f">BI{strlen}B", MPF_BIN32, strlen, *binstr))
        elif message.typ == "uint":
            if message.value < (1 << 8):
                return bytearray(struct.pack(">BB", MPF_UINT8, message.value))
            if message.value < (1 << 16):
                return bytearray(struct.pack(">BH", MPF_UINT16, message.value))
            if message.value < (1 << 32):
                return bytearray(struct.pack(">BI", MPF_UINT32, message.value))
            return bytearray(struct.pack(">BQ", MPF_UINT64, message.value))
        elif message.typ == "int":
            if -32 <= message.value < 128:
                return bytearray(struct.pack("b", message.value))
            if -(1 << 7) <= message.value < (1 << 7):
                return bytearray(struct.pack(">Bb", MPF_INT8, message.value))
            if -(1 << 15) <= message.value < (1 << 15):
                return bytearray(struct.pack(">Bh", MPF_INT16, message.value))
            if -(1 << 31) <= message.value < (1 << 31):
                return bytearray(struct.pack(">Bi", MPF_INT32, message.value))
            return bytearray(struct.pack(">Bq", MPF_INT64, message.value))
        elif message.typ == "nil":
            return bytearray(struct.pack("B", MPF_NIL))
        elif message.typ == "bool":
            return bytearray(struct.pack("B", MPF_TRUE if message.value else MPF_FALSE))

        return bytearray()

    @staticmethod
    def _normalize_key(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="replace")
        return str(value)
