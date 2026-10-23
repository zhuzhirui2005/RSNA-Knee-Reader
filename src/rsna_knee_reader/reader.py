"""DICOM windowing and bounded image pages, extracted from the competition reader."""

import base64
from functools import lru_cache
import io
import json

import numpy as np
from PIL import Image, ImageDraw
from pydicom.pixels import apply_modality_lut, apply_voi_lut
from mcp.types import CallToolResult, ImageContent, TextContent

from .catalog import Catalog
from .storage import DicomStore

PREVIEW_EDGE = 512
PREVIEW_PAGE = 4


def orientation(ds) -> dict:
    iop = ds.get("ImageOrientationPatient")
    if iop is None:
        return {}
    def label(vector):
        axis = int(np.argmax(np.abs(vector)))
        return ("L", "P", "H")[axis] if vector[axis] > 0 else ("R", "A", "F")[axis]
    horizontal, vertical = np.asarray(iop[:3], float), np.asarray(iop[3:], float)
    return {"left": label(-horizontal), "right": label(horizontal),
            "top": label(-vertical), "bottom": label(vertical)}


def first_float(value) -> float:
    return float(value[0] if hasattr(value, "__len__") and not isinstance(value, str) else value)


def linear_window(array, center: float, width: float):
    if width < 1 or not np.isfinite([center, width]).all():
        raise ValueError("Window center/width must be finite and width must be at least 1.")
    if width == 1:
        return (array > center - 0.5).astype(float)
    return np.clip((array - (center - 0.5)) / (width - 1) + 0.5, 0, 1)


class Reader:
    def __init__(self, catalog: Catalog, store: DicomStore):
        self.catalog, self.store = catalog, store
        # Caches belong to this reader and hold only a small number of decoded slices.
        self.pixels = lru_cache(maxsize=48)(self._pixels)
        self.series_window = lru_cache(maxsize=64)(self._series_window)

    def series(self, case_id: str, series_id: str):
        case = self.catalog.case(case_id)
        for series in case["series"]:
            if series["series_id"] == series_id:
                return case, series
        raise ValueError("Unknown series_id; use get_case.")

    def _pixels(self, path: str, study_uid: str):
        ds = self.store.read(path, study_uid)
        if int(ds.get("SamplesPerPixel", 1)) != 1 or int(ds.get("NumberOfFrames", 1)) != 1:
            raise ValueError("This release reads single-frame grayscale MRI.")
        return ds, apply_modality_lut(ds.pixel_array, ds).astype(np.float32)

    def _series_window(self, study_uid: str, paths: tuple[str, ...]):
        samples = [self.pixels(paths[i], study_uid)[1]
                   for i in np.linspace(0, len(paths) - 1, min(5, len(paths))).astype(int)]
        values = np.concatenate([array.ravel()[::4] for array in samples])
        finite = values[np.isfinite(values)]
        if not len(finite):
            raise ValueError("Series contains no finite pixel values.")
        low, high = np.percentile(finite, [0.5, 99.5])
        return float(low), float(max(high, low + 1))

    def list_cases(self, offset: int = 0, limit: int = 100) -> dict:
        ids = sorted(self.catalog.cases)
        end = min(len(ids), offset + limit)
        return {"case_ids": ids[offset:end], "total": len(ids),
                "next_offset": end if end < len(ids) else None}

    def get_case(self, case_id: str) -> dict:
        case = self.catalog.case(case_id)
        summary = []
        for series in case["series"]:
            ds = self.store.read(series["files"][0]["path"], case["study_uid"], stop_before_pixels=True)
            summary.append({"series_id": series["series_id"], "description": series["description"],
                            "protocol": series["protocol"], "slices": len(series["files"]),
                            "native_size": [int(ds.Columns), int(ds.Rows)],
                            "pixel_spacing_mm": [float(v) for v in ds.get("PixelSpacing", [])],
                            "slice_thickness_mm": float(ds.SliceThickness) if "SliceThickness" in ds else None,
                            "edge_orientation": orientation(ds), "sorting": series["sorting"]})
        return {"case_id": case_id, "report": case["report"], "series": summary,
                "image_delivery": {"preview_long_edge": PREVIEW_EDGE, "preview_page_limit": PREVIEW_PAGE,
                                   "preview_format": "JPEG", "native_page_limit": 1, "native_format": "PNG"}}

    def render(self, case: dict, series: dict, number: int, case_id: str,
               center, width, window: str, crop, detail: str):
        ds, array = self.pixels(series["files"][number - 1]["path"], case["study_uid"])
        if center is not None:
            normalized = linear_window(array, center, width)
            used = {"center": center, "width": width, "source": "requested"}
        elif window == "dicom" and ds.get("VOILUTSequence"):
            mapped = apply_voi_lut(array, ds, prefer_lut=True)
            depth = int(ds.VOILUTSequence[0].LUTDescriptor[2])
            normalized = np.clip(mapped / (2 ** depth - 1), 0, 1)
            used = {"source": "dicom_voi_lut"}
        elif window == "dicom" and "WindowCenter" in ds and "WindowWidth" in ds:
            c, w = first_float(ds.WindowCenter), first_float(ds.WindowWidth)
            function = str(ds.get("VOILUTFunction", "LINEAR")).upper()
            if w <= 0:
                raise ValueError("DICOM WindowWidth must be positive; try window='auto'.")
            if function == "SIGMOID":
                normalized = 1 / (1 + np.exp(np.clip(-4 * (array - c) / w, -80, 80)))
            elif function == "LINEAR_EXACT":
                normalized = np.clip((array - c) / w + 0.5, 0, 1)
            else:
                normalized = linear_window(array, c, w)
            used = {"center": c, "width": w, "source": "dicom", "function": function}
        else:
            low, high = self.series_window(case["study_uid"], tuple(f["path"] for f in series["files"]))
            normalized = np.clip((array - low) / (high - low), 0, 1)
            used = {"center": (high + low) / 2, "width": high - low, "source": "series_percentiles"}
        if str(ds.get("PhotometricInterpretation", "MONOCHROME2")) == "MONOCHROME1":
            normalized = 1 - normalized
        image = Image.fromarray(np.rint(normalized * 255).astype("uint8"))
        native_size = list(image.size)
        if crop is not None:
            x, y, w, h = crop
            if min(x, y) < 0 or min(w, h) <= 0 or x + w > image.width or y + h > image.height:
                raise ValueError("crop must be inside the native image: [x, y, width, height].")
            image = image.crop((x, y, x + w, y + h))
        source_size = list(image.size)
        if detail == "preview":
            image.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE), Image.Resampling.LANCZOS)
        display_size = list(image.size)
        edges = orientation(ds)
        tile = Image.new("L", (image.width + 32, image.height + 48), 0)
        tile.paste(image, (16, 24))
        draw = ImageDraw.Draw(tile)
        draw.text((18, 2), f'{case_id} {series["series_id"]} #{number}', fill=255)
        draw.text((2, tile.height // 2), edges.get("left", "?"), fill=255)
        draw.text((tile.width - 12, tile.height // 2), edges.get("right", "?"), fill=255)
        draw.text((tile.width - 30, 2), edges.get("top", "?"), fill=255)
        draw.text((tile.width // 2, tile.height - 16), edges.get("bottom", "?"), fill=255)
        return tile, {"slice": number, "native_size": native_size, "display_size": display_size,
                      "window": used, "crop": crop, "resized": display_size != source_size,
                      "edge_orientation": edges, "detail": detail}

    def read_slices(self, case_id: str, series_id: str, start: int = 1, count: int = 4,
                    layout: str = "grid", detail: str = "preview", window: str = "dicom",
                    window_center=None, window_width=None, crop=None) -> CallToolResult:
        case, series = self.series(case_id, series_id)
        total = len(series["files"])
        if not 1 <= start <= total or count < 1:
            raise ValueError(f"start must be between 1 and {total}; count must be positive.")
        if (window_center is None) != (window_width is None):
            raise ValueError("Set both window_center and window_width, or neither.")
        limit = 1 if detail == "native" or layout == "individual" else PREVIEW_PAGE
        end = min(total, start + min(count, limit) - 1)
        rendered = [self.render(case, series, n, case_id, window_center, window_width, window, crop, detail)
                    for n in range(start, end + 1)]
        tiles, details = zip(*rendered)
        if len(tiles) == 1:
            sheet = tiles[0]
        else:
            w, h = max(t.width for t in tiles), max(t.height for t in tiles)
            sheet = Image.new("L", (2 * w, ((len(tiles) + 1) // 2) * h), 0)
            for i, tile in enumerate(tiles):
                sheet.paste(tile, ((i % 2) * w, (i // 2) * h))
        stream = io.BytesIO()
        if detail == "native":
            sheet.save(stream, format="PNG", compress_level=6)
            mime = "image/png"
        else:
            sheet.save(stream, format="JPEG", quality=88, optimize=True)
            mime = "image/jpeg"
        data = stream.getvalue()
        metadata = {"case_id": case_id, "series_id": series_id, "start": start, "end": end, "total": total,
                    "next_start": end + 1 if end < total else None, "layout": layout, "detail": detail,
                    "page_slice_limit": limit, "slices": details, "image_size": list(sheet.size),
                    "encoded_bytes": len(data)}
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(metadata)),
                                      ImageContent(type="image", mime_type=mime,
                                                   data=base64.b64encode(data).decode())])
