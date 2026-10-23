"""Generate tiny, visibly synthetic DICOM studies; no patient data is distributed."""

from pathlib import Path

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

from .catalog import index_directory, write_json


def demo_uid(*parts):
    return generate_uid(entropy_srcs=["rsna-knee-reader-demo", *map(str, parts)])


def make_demo(destination: Path) -> Path:
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("Choose an empty demo directory.")
    data = destination / "dicom"
    reports = {}
    y, x = np.mgrid[:256, :640]
    for case in range(1, 3):
        study_uid = demo_uid("study", case)
        reports[study_uid] = "SYNTHETIC DEMONSTRATION ONLY. Moving geometric shapes, not a patient MRI."
        for series in range(1, 3):
            series_uid = demo_uid("series", case, series)
            folder = data / study_uid / series_uid
            folder.mkdir(parents=True, exist_ok=True)
            for index in range(1, 7):
                instance_uid = demo_uid("instance", case, series, index)
                meta = FileMetaDataset()
                meta.MediaStorageSOPClassUID = MRImageStorage
                meta.MediaStorageSOPInstanceUID = instance_uid
                meta.TransferSyntaxUID = ExplicitVRLittleEndian
                ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
                ds.SOPClassUID, ds.SOPInstanceUID = MRImageStorage, instance_uid
                ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
                ds.PatientName, ds.PatientID = "SYNTHETIC^DEMO", f"DEMO{case}"
                ds.Modality, ds.SeriesNumber = "MR", series
                ds.SeriesDescription = f"Synthetic series {series}"
                ds.ProtocolName = "Synthetic shapes"
                ds.ImageType = ["DERIVED", "SECONDARY"]
                ds.InstanceNumber = 7 - index  # Geometry must win over file/instance order.
                ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
                ds.ImagePositionPatient = [0, 0, index * 3.5]
                ds.PixelSpacing, ds.SliceThickness = [0.5, 0.5], 3.5
                ds.Rows, ds.Columns = 256, 640
                ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
                ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
                ds.RescaleIntercept, ds.RescaleSlope = 0, 1
                ds.WindowCenter, ds.WindowWidth = 1000, 2000
                shape = (x - (100 + 55 * index)) ** 2 + (y - 128) ** 2 < (25 + 5 * series) ** 2
                array = (x / 4 + y / 3 + shape * 1500).astype("<u2")
                ds.PixelData = array.tobytes()
                ds.save_as(folder / f"slice_{7-index:03d}.dcm", enforce_file_format=True)
    catalog = destination / "catalog.json"
    write_json(destination / "reports.json", reports)
    index_directory(data, catalog, reports)
    return catalog
