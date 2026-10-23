"""Plain DICOM files and byte-preserving, per-study .dcmz archives."""

import hashlib
import io
import json
import os
from pathlib import Path
import zipfile

import numpy as np
import pydicom
import zstandard as zstd


def encode(data: bytes) -> bytes:
    count = len(data) // 2
    words = np.frombuffer(data[:2 * count], dtype="<u2")
    delta = np.diff(words, prepend=np.zeros(1, np.uint16)).astype("<u2")
    shuffled = delta.view(np.uint8).reshape(-1, 2).T.copy().tobytes() + data[2 * count:]
    return zstd.ZstdCompressor(level=6, write_checksum=True).compress(shuffled)


def decode(data: bytes) -> bytes:
    shuffled = zstd.ZstdDecompressor().decompress(data)
    count = len(shuffled) // 2
    words = np.frombuffer(shuffled[:2 * count], np.uint8).reshape(2, count).T.copy().reshape(-1).view("<u2")
    return np.cumsum(words, dtype=np.uint16).astype("<u2").tobytes() + shuffled[2 * count:]


def within(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Catalog paths must remain inside the configured data directory.")
    return path


class DicomStore:
    def __init__(self, data_root: Path, archive_root: Path | None = None):
        self.data_root = Path(data_root).resolve()
        self.archive_root = Path(archive_root).resolve() if archive_root else None

    def archive_path(self, study_uid: str) -> Path:
        if self.archive_root is None:
            raise FileNotFoundError("Original DICOM is missing and no archive directory was configured.")
        return self.archive_root / (hashlib.sha256(study_uid.encode()).hexdigest()[:24] + ".dcmz")

    def read(self, relative: str, study_uid: str, **kwargs):
        path = within(self.data_root, relative)
        if path.is_file():
            return pydicom.dcmread(path, **kwargs)
        with zipfile.ZipFile(self.archive_path(study_uid)) as archive:
            data = decode(archive.read(relative))
        return pydicom.dcmread(io.BytesIO(data), **kwargs)

    def pack(self, case: dict) -> Path:
        target = self.archive_path(case["study_uid"])
        if target.exists():
            raise FileExistsError(f"Archive already exists: {target.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        manifest = {"format_version": 1, "study_uid": case["study_uid"],
                    "codec": "u16_delta_shuffle_zstd6_v1", "files": {}}
        paths = sorted({f["path"] for s in case["series"] for f in s["files"]})
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
                for relative in paths:
                    original = within(self.data_root, relative).read_bytes()
                    packed = encode(original)
                    if decode(packed) != original:
                        raise RuntimeError("DICOM byte round-trip failed.")
                    archive.writestr(relative, packed)
                    manifest["files"][relative] = len(original)
                archive.writestr("_manifest.json", json.dumps(manifest))
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def restore(self, study_uid: str, destination: Path) -> None:
        destination = Path(destination).resolve()
        with zipfile.ZipFile(self.archive_path(study_uid)) as archive:
            manifest = json.loads(archive.read("_manifest.json"))
            if manifest["study_uid"] != study_uid or manifest["codec"] != "u16_delta_shuffle_zstd6_v1":
                raise ValueError("Unexpected archive study or codec.")
            for relative, size in manifest["files"].items():
                path = within(destination, relative)
                original = decode(archive.read(relative))
                if len(original) != size:
                    raise ValueError("Restored DICOM has an unexpected length.")
                if path.exists() and path.read_bytes() != original:
                    raise FileExistsError(f"Refusing to replace a different file: {relative}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)
