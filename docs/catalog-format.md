# Catalog format

The `index` command creates UTF-8 JSON. All image paths are relative to `--data-root`:

```json
{
  "format_version": 1,
  "cases": {
    "CASE0001": {
      "study_uid": "1.2.826.0.1.3680043.8.498.123",
      "report": "Synthetic report; not a real patient.",
      "series": [
        {
          "series_id": "S01",
          "description": "Synthetic sequence",
          "protocol": "Synthetic shapes",
          "sorting": "geometric_slice_position",
          "files": [
            {"path": "study/series/001.dcm"},
            {"path": "study/series/002.dcm"}
          ]
        }
      ]
    }
  }
}
```

`files` is the display order. The indexer sorts using the slice normal derived from `ImageOrientationPatient` and the projection of `ImagePositionPatient`; it falls back to `InstanceNumber` and filename if common geometric ordering is unavailable. `get_case` reports which sort was used.

The service returns only the explicitly defined report and series display fields. Do not put reference labels or private evaluation material in a public reading catalog. Case aliases are not a substitute for de-identifying report text, burned-in image text or DICOM originals.

The standalone catalog is intentionally independent of training folds, gold/nongold selections and experiment status. Existing competition catalogs used project-root paths and multiple configuration files; regenerate this format from your own authorized data rather than copying those private indexes into the repository.
