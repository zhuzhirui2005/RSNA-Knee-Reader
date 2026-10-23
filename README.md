# RSNA Knee Reader

[中文说明](README.zh-CN.md)

An MCP server that lets multimodal clients browse knee MRI studies stored on a server: read a report, enumerate series, turn through small pages of actual DICOM images, and inspect native-resolution details when needed.

The reader was developed for the RSNA Knee Abnormality Detection competition. The complete competition solution achieved **21st place, Solo Gold, Private AUC 0.955**. This repository contains the reading infrastructure, not the trained competition models or an automatic diagnostic system.

## What is included

- Three read-only MCP tools: `list_cases`, `get_case`, and `read_slices`.
- Geometric slice ordering, orientation markers, DICOM display windowing and consistent series-level automatic windowing.
- JPEG preview grids of at most four slices; single-image PNG detail with native-coordinate crops.
- Plain DICOM files or byte-preserving study archives with random access to an individual file.
- Standard stdio and stateless Streamable HTTP transports, optional bearer authentication, synthetic demo data, and tests.

There are no patient images, reports, gold answers, credentials, model weights, account-specific tunnels, or paid inference API calls in the package. The MCP client supplies the multimodal model; this server supplies reports and rendered images.

## Quick start

Python 3.11 or newer is required:

```sh
git clone https://github.com/zhuzhirui2005/rsna-knee-reader.git
cd rsna-knee-reader
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -e .

rsna-knee-reader demo .demo
rsna-knee-reader serve --catalog .demo/catalog.json --data-root .demo/dicom
```

The final command starts a **stdio MCP server**, so it waits for a client rather than showing an interactive viewer. The demo generates two synthetic studies containing moving geometric shapes. It needs no competition access, GPU, or API key.

For clients that launch stdio servers, adapt [the example configuration](examples/mcp-client.json). Use absolute paths so the client does not depend on its working directory.

For HTTP:

```sh
rsna-knee-reader serve --catalog .demo/catalog.json --data-root .demo/dicom --transport http
```

The MCP endpoint is `http://127.0.0.1:8768/mcp`; the health endpoint is `/healthz`. HTTP supports the modern stateless protocol and legacy MCP initialization through the official SDK. See [deployment](docs/deployment.md) for remote hosting, authentication and containers.

## Add your own studies

Place authorized, de-identified single-frame grayscale MR files under a data directory. Directory names are arbitrary; the indexer groups by DICOM study and series UIDs and orders slices by their geometric positions. Files need the `.dcm` extension.

Reports are optional. Supply a UTF-8 JSON object mapping each `StudyInstanceUID` to its report text:

```json
{"1.2.826.0.1.3680043.8.498.123": "A synthetic example report."}
```

```sh
rsna-knee-reader index --data-root data/dicom --reports data/reports.json --output data/catalog.json
rsna-knee-reader serve --catalog data/catalog.json --data-root data/dicom
```

Omit `--reports` to serve images without reports. Re-indexing preserves existing case IDs, report text unless replaced, and catalog entries whose originals have already been archived. The server reloads the catalog after its file changes. Restart the server if you replace image contents at an existing path, because decoded pixels are cached.

See [catalog format](docs/catalog-format.md). The tool response exposes case aliases, series descriptions, reports, and display metadata; it does not return filesystem paths or reference labels. **Indexing does not anonymize the original DICOM files or report text.**

This release indexes classic single-frame monochrome MRI. Enhanced multi-frame DICOM is rejected explicitly because its per-frame geometry needs a separate implementation. Compressed pixel transfer syntaxes may require optional decoders:

```sh
python -m pip install -e ".[compressed]"
```

## Read a case

| Tool | Example arguments | Result |
|---|---|---|
| `list_cases` | `{"offset":0,"limit":100}` | Case IDs and `next_offset` |
| `get_case` | `{"case_id":"CASE0001"}` | Report, all series, dimensions and orientation |
| `read_slices` | `{"case_id":"CASE0001","series_id":"S01","start":1,"count":4}` | One preview grid plus paging metadata |
| `read_slices` | `{"case_id":"CASE0001","series_id":"S01","start":3,"count":1,"detail":"native","layout":"individual","crop":[40,30,160,160]}` | One detailed PNG crop |

Slice numbers start at **1**. Follow the returned `next_start` until it is `null`; a large requested count is capped without skipping the intervening images. Each call returns exactly one image block.

Preview slice content has a longest edge of at most 512 pixels, with an additional label border. A four-slice grid can therefore be larger than 512 pixels. Native mode preserves spatial resolution **after display windowing to 8 bits**; the returned PNG is not the raw DICOM intensity array. Only the `.dcmz` archive promises original-file byte preservation.

`crop=[x,y,width,height]` uses original image coordinates before resizing or adding borders. To change the display, specify both `window_center` and `window_width`, or set `window="auto"`. Automatic windowing samples the series consistently, rather than normalizing each page independently. Orientation markers show the dominant patient axis and do not reorient the image.

Read serially within one case. Parallelize independent cases if the client supports workers, and return compact results to a coordinator rather than collecting every worker's images in one conversation. The [Chinese annotation prompt](prompts/knee-annotation.zh-CN.md) and [probability output schema](examples/probability-output.schema.json) demonstrate the competition workflow. The server itself does not infer or store diagnoses.

## Lossless storage

```sh
rsna-knee-reader archive --catalog data/catalog.json --data-root data/dicom --archives data/archives
rsna-knee-reader serve --catalog data/catalog.json --data-root data/dicom --archives data/archives
```

Archives preserve **the entire original DICOM byte stream**, including headers and original pixel encoding. The codec uses reversible 16-bit delta coding, byte shuffling and Zstandard within a per-study ZIP container. A read decodes one member, without extracting the whole study. These archives are specific to this reader, not a standard DICOM transfer syntax.

The archive command verifies each byte round-trip and never deletes the originals. The server first tries the original path, then its archive. Existing archives are not silently replaced. To restore files:

```sh
rsna-knee-reader restore --archives data/archives --study-uid YOUR_STUDY_UID --destination data/restored
```

The study UID is available in the local catalog. Restoration keeps paths relative to the original data root.

## Development

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m build
```

Tests generate synthetic DICOMs and cover slice ordering, page continuity, native crops, windowing, lossless restoration, MCP tool calls, modern/legacy HTTP and optional authentication. No real cases are needed.

The extracted implementation uses the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), [pydicom](https://github.com/pydicom/pydicom), NumPy, Pillow and Zstandard. It upgrades the original competition server to SDK v2, which provides the protocol compatibility previously handled by a project-specific shim; see the [SDK migration guide](https://py.sdk.modelcontextprotocol.io/migration/).

## Scope and license

This is research reading infrastructure, not a validated clinical device. Data licensing and permission to send rendered images and reports to a chosen model service remain separate from the software license. The originals stay on the server, but the requested images and reports are transmitted to the connected client.

Code is licensed under [MIT](LICENSE). No competition dataset or third-party model weights are redistributed. See [provenance](docs/provenance.md) for the extraction boundary.
