"""Build a report/image-only catalog; never import diagnosis reference labels."""

from collections import defaultdict
import json
from pathlib import Path

import numpy as np
import pydicom


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class Catalog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._mtime = None
        self._cases = {}

    @property
    def cases(self) -> dict:
        mtime = self.path.stat().st_mtime_ns
        if self._mtime != mtime:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("format_version") != 1:
                raise ValueError("Expected catalog format_version=1.")
            self._cases = data["cases"]
            self._mtime = mtime
        return self._cases

    def case(self, case_id: str) -> dict:
        try:
            return self.cases[case_id]
        except KeyError:
            raise ValueError("Unknown case_id; use list_cases.") from None


def index_directory(data_root: Path, output: Path, reports: dict | None = None, prefix: str = "CASE") -> dict:
    """Index classic single-frame MRI. Preserve existing IDs when adding studies."""
    data_root = data_root.resolve()
    grouped = defaultdict(lambda: defaultdict(list))
    for path in sorted(data_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".dcm":
            continue
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        if str(ds.get("Modality", "")) != "MR":
            continue
        if int(ds.get("NumberOfFrames", 1)) != 1 or int(ds.get("SamplesPerPixel", 1)) != 1:
            raise ValueError(f"Only single-frame grayscale MRI is indexed in this release: {path.name}")
        grouped[str(ds.StudyInstanceUID)][str(ds.SeriesInstanceUID)].append((path, ds))
    if not grouped:
        raise ValueError("No single-frame MR .dcm files found.")
    previous = Catalog(output).cases if output.exists() else {}
    known = {case["study_uid"]: case_id for case_id, case in previous.items()}
    cases, counter = {}, 1
    used = set(previous)
    for study_uid, series_groups in sorted(grouped.items()):
        case_id = known.get(study_uid)
        if case_id is None:
            while f"{prefix}{counter:04d}" in used:
                counter += 1
            case_id = f"{prefix}{counter:04d}"
            used.add(case_id)
        series = []
        ordered = sorted(series_groups.items(), key=lambda item: (
            int(item[1][0][1].get("SeriesNumber", 0)), item[0]))
        for number, (_, entries) in enumerate(ordered, 1):
            first = entries[0][1]
            geometric = all("ImageOrientationPatient" in ds and "ImagePositionPatient" in ds for _, ds in entries)
            if geometric:
                orientation = np.asarray(first.ImageOrientationPatient, dtype=float)
                geometric = all(np.allclose(ds.ImageOrientationPatient, orientation, atol=1e-4) for _, ds in entries)
            if geometric:
                normal = np.cross(orientation[:3], orientation[3:])
                entries.sort(key=lambda item: (float(np.dot(item[1].ImagePositionPatient, normal)),
                                               int(item[1].get("InstanceNumber", 0)), item[0].name))
            else:
                entries.sort(key=lambda item: (int(item[1].get("InstanceNumber", 0)), item[0].name))
            series.append({"series_id": f"S{number:02d}",
                           "description": str(first.get("SeriesDescription", "")),
                           "protocol": str(first.get("ProtocolName", "")),
                           "sorting": "geometric_slice_position" if geometric else "instance_number",
                           "files": [{"path": p.relative_to(data_root).as_posix()} for p, _ in entries]})
        report = (reports or {}).get(study_uid, previous.get(case_id, {}).get("report", ""))
        if not isinstance(report, str):
            raise ValueError("Reports JSON must map each StudyInstanceUID to a report string.")
        cases[case_id] = {"study_uid": study_uid, "report": report, "series": series}
    # Retain archived studies that no longer have an uncompressed directory.
    write_json(output, {"format_version": 1, "cases": previous | cases})
    return previous | cases
