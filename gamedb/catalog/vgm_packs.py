"""Mirror checksum-pinned soundtrack archives."""

from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen


def verified(path, record):
    if not path.is_file() or path.is_symlink() or path.stat().st_size != record["size"]:
        return False
    with path.open("rb") as stream:
        return sha256(stream.read(record["size"] + 1)).hexdigest() == record["sha256"]


def save_pack(record, directory, cached):
    filename = record["name"] + record["extension"]
    if Path(filename).name != filename or record["extension"] not in {".zip", ".7z"}:
        raise ValueError("Invalid soundtrack filename")
    destination = directory / filename
    if verified(destination, record):
        return "reused", destination
    request = Request(record["download"], headers={"User-Agent": "GameDB/2.0 (retail soundtrack library)"})
    stream = cached.open("rb") if verified(cached, record) else urlopen(request, timeout=45)
    with stream, NamedTemporaryFile(dir=directory, prefix=".vgm-", suffix=".part", delete=False) as sink:
        temporary = Path(sink.name)
        try:
            data = stream.read(record["size"] + 1)
            if len(data) != record["size"] or sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("Soundtrack archive differs from the reviewed copy")
            sink.write(data)
            sink.flush()
            sink.close()
            temporary.chmod(0o644)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return "downloaded", destination
