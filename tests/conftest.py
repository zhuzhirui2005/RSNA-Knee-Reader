import pytest

from rsna_knee_reader.catalog import Catalog
from rsna_knee_reader.demo import make_demo
from rsna_knee_reader.reader import Reader
from rsna_knee_reader.storage import DicomStore


@pytest.fixture
def setup_case(tmp_path):
    directory = tmp_path / "demo"
    catalog_path = make_demo(directory)
    catalog = Catalog(catalog_path)
    store = DicomStore(directory / "dicom", directory / "archives")
    return directory, Reader(catalog, store)
