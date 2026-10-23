import asyncio
import base64
import io
import json
import sys

import numpy as np
from PIL import Image
import pydicom
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from rsna_knee_reader.catalog import Catalog, index_directory
from rsna_knee_reader.reader import Reader, linear_window
from rsna_knee_reader.server import create_server
from rsna_knee_reader.storage import DicomStore, decode, encode, within


def unpack(result):
    return json.loads(result.content[0].text), Image.open(io.BytesIO(base64.b64decode(result.content[1].data)))


def test_geometry_and_preview_pagination(setup_case):
    _, reader = setup_case
    info = reader.get_case("CASE0001")
    assert info["series"][0]["sorting"] == "geometric_slice_position"
    case, series = reader.series("CASE0001", "S01")
    positions = [float(reader.store.read(f["path"], case["study_uid"]).ImagePositionPatient[2]) for f in series["files"]]
    assert positions == sorted(positions)
    page, image = unpack(reader.read_slices("CASE0001", "S01", count=12))
    assert (page["start"], page["end"], page["next_start"]) == (1, 4, 5)
    assert image.format == "JPEG" and len(page["slices"]) == 4
    assert max(page["slices"][0]["display_size"]) == 512
    tail, _ = unpack(reader.read_slices("CASE0001", "S01", start=page["next_start"]))
    assert (tail["start"], tail["end"], tail["next_start"]) == (5, 6, None)


def test_native_crop_and_window(setup_case):
    _, reader = setup_case
    page, image = unpack(reader.read_slices("CASE0001", "S01", detail="native", count=4,
                                         crop=[10, 20, 50, 60], window_center=900, window_width=1800))
    assert image.format == "PNG" and image.size == (82, 108)
    assert page["end"] == 1 and page["next_start"] == 2
    assert page["slices"][0]["display_size"] == [50, 60]
    assert page["slices"][0]["native_size"] == [640, 256]
    assert page["slices"][0]["resized"] is False
    assert page["slices"][0]["window"]["source"] == "requested"
    with pytest.raises(ValueError, match="both"):
        reader.read_slices("CASE0001", "S01", window_center=1)
    with pytest.raises(ValueError, match="crop"):
        reader.read_slices("CASE0001", "S01", crop=[630, 0, 30, 30])


def test_auto_window_consistent_across_pages(setup_case):
    _, reader = setup_case
    first, _ = unpack(reader.read_slices("CASE0001", "S01", window="auto"))
    last, _ = unpack(reader.read_slices("CASE0001", "S01", start=5, window="auto"))
    windows = [s["window"] for s in first["slices"] + last["slices"]]
    assert all(w == windows[0] for w in windows)


def test_linear_dicom_threshold():
    np.testing.assert_array_equal(linear_window(np.array([0, .5, 1]), 1, 1), [0, 0, 1])
    np.testing.assert_allclose(linear_window(np.array([0, 1, 2]), 1, 2), [0, 1, 1])


@pytest.mark.parametrize("size", [0, 1, 2, 511, 4096])
def test_archive_codec_preserves_odd_and_even_bytes(size):
    original = np.random.default_rng(7).integers(0, 256, size, dtype=np.uint8).tobytes()
    assert decode(encode(original)) == original


def test_archives_serve_without_originals_and_restore_exactly(setup_case):
    directory, reader = setup_case
    case = reader.catalog.case("CASE0001")
    files = [f["path"] for s in case["series"] for f in s["files"]]
    originals = {p: (directory / "dicom" / p).read_bytes() for p in files}
    reader.store.pack(case)
    for relative in files:
        (directory / "dicom" / relative).unlink()
    page, image = unpack(reader.read_slices("CASE0001", "S01"))
    assert page["end"] == 4 and image.format == "JPEG"
    reader.store.restore(case["study_uid"], directory / "restored")
    assert all((directory / "restored" / p).read_bytes() == data for p, data in originals.items())


def test_catalog_reload_preserves_ids_and_omits_reference_fields(setup_case):
    directory, reader = setup_case
    original = dict(reader.catalog.cases)
    result = index_directory(directory / "dicom", directory / "catalog.json")
    assert result == original
    data = json.loads((directory / "catalog.json").read_text())
    data["cases"]["CASE0001"]["report"] = "Updated synthetic report"
    data["cases"]["CASE0001"]["reference_labels"] = {"ACL": 1}
    (directory / "catalog.json").write_text(json.dumps(data))
    response = reader.get_case("CASE0001")
    assert response["report"] == "Updated synthetic report"
    assert "reference_labels" not in response and "study_uid" not in response
    assert reader.list_cases(limit=1)["next_offset"] == 1


def test_data_path_boundary(tmp_path):
    with pytest.raises(ValueError, match="inside"):
        within(tmp_path, "../outside.dcm")


def test_index_rejects_multiframe_instead_of_misordering(setup_case):
    directory, reader = setup_case
    case = reader.catalog.case("CASE0001")
    path = directory / "dicom" / case["series"][0]["files"][0]["path"]
    ds = pydicom.dcmread(path)
    ds.NumberOfFrames = 2
    ds.save_as(path, enforce_file_format=True)
    with pytest.raises(ValueError, match="single-frame"):
        index_directory(directory / "dicom", directory / "catalog.json")


def test_standard_mcp_client_and_invalid_arguments(setup_case):
    _, reader = setup_case
    async def exercise():
        async with Client(create_server(reader)) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == {"list_cases", "get_case", "read_slices"}
            result = await client.call_tool("read_slices", {"case_id": "CASE0001", "series_id": "S01"})
            assert result.is_error is not True
            assert len(result.content) == 2 and result.content[1].mime_type == "image/jpeg"
            invalid = await client.call_tool("read_slices", {"case_id": "CASE0001", "series_id": "S01", "start": 0})
            assert invalid.is_error is True
    asyncio.run(exercise())


def test_stdio_cli_process(setup_case):
    directory, _ = setup_case
    async def exercise():
        process = StdioServerParameters(command=sys.executable, args=[
            "-m", "rsna_knee_reader", "serve", "--catalog", str(directory / "catalog.json"),
            "--data-root", str(directory / "dicom")])
        async with Client(process, read_timeout_seconds=20) as client:
            result = await client.call_tool("get_case", {"case_id": "CASE0001"})
            assert result.is_error is not True
            assert "SYNTHETIC" in result.content[0].text
    asyncio.run(exercise())
