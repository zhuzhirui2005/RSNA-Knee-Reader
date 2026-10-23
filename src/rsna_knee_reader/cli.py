import argparse
import json
import os
from pathlib import Path

from .catalog import Catalog, index_directory
from .demo import make_demo
from .reader import Reader
from .server import create_http_app, create_server
from .storage import DicomStore


def main():
    parser = argparse.ArgumentParser(description="Serve server-side MRI images and reports through MCP.")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Create synthetic cases for a data-free quick start")
    demo.add_argument("destination", type=Path)
    index = commands.add_parser("index", help="Index single-frame grayscale MR .dcm files")
    index.add_argument("--data-root", type=Path, required=True)
    index.add_argument("--output", type=Path, required=True)
    index.add_argument("--reports", type=Path, help="JSON mapping StudyInstanceUID to report text")
    index.add_argument("--case-prefix", default="CASE")
    serve = commands.add_parser("serve", help="Run a read-only MCP server")
    pack = commands.add_parser("archive", help="Create lossless study archives; retain original files")
    restore = commands.add_parser("restore", help="Restore an archived study's original bytes")
    for command in (serve, pack):
        command.add_argument("--catalog", type=Path, required=True)
        command.add_argument("--data-root", type=Path, required=True)
        command.add_argument("--archives", type=Path, required=command is pack)
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8768)
    serve.add_argument("--public-host", help="Additional allowed HTTP Host, e.g. reader.example.org")
    pack.add_argument("--case-id", help="Archive just this case; default: all cases")
    restore.add_argument("--archives", type=Path, required=True)
    restore.add_argument("--study-uid", required=True)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "demo":
        print(f"Created synthetic catalog: {make_demo(args.destination)}")
    elif args.command == "index":
        reports = json.loads(args.reports.read_text(encoding="utf-8")) if args.reports else None
        cases = index_directory(args.data_root, args.output, reports, args.case_prefix)
        print(f"Indexed {len(cases)} cases: {args.output}")
    elif args.command == "restore":
        DicomStore(args.destination, args.archives).restore(args.study_uid, args.destination)
        print(f"Restored to: {args.destination}")
    else:
        catalog, store = Catalog(args.catalog), DicomStore(args.data_root, args.archives)
        if args.command == "archive":
            cases = {args.case_id: catalog.case(args.case_id)} if args.case_id else catalog.cases
            for case_id, case in cases.items():
                print(f"{case_id}: {store.pack(case).name}")
        else:
            reader = Reader(catalog, store)
            # Fail before opening the transport if the catalog cannot be loaded.
            catalog.cases
            if args.transport == "stdio":
                create_server(reader).run(transport="stdio")
            else:
                import uvicorn
                app = create_http_app(reader, os.environ.get("RSNA_READER_TOKEN"), args.public_host)
                uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)
