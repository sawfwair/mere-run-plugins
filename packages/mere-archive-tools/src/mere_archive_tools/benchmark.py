"""Generate and score repeatable archive-search benchmarks."""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import io
import json
import pathlib
import shutil
import sqlite3
import struct
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
import zlib
from collections.abc import Callable, Iterable
from importlib import resources
from typing import cast

from . import extractors

BENCHMARK_CONTRACT = "mere.run/archive-benchmark.v1"
REPORT_CONTRACT = "mere.run/archive-benchmark-report.v1"
SYNTHETIC_DATASET_ID = "mere-archive-gauntlet"
HARBOURLINE_DATASET_ID = "harbourline-operations-archive"
VIDORE_DATASET_ID = "vidore-government-reports"
GOVDOCS_DATASET_ID = "govdocs1-shard-000"
DATASET_IDS = (SYNTHETIC_DATASET_ID, HARBOURLINE_DATASET_ID, VIDORE_DATASET_ID, GOVDOCS_DATASET_ID)
VIDORE_ROWS_URL = "https://datasets-server.huggingface.co/rows"
JsonMap = dict[str, object]
SearchFunction = Callable[[str, int], JsonMap]


class BenchmarkError(RuntimeError):
    """Reports an invalid fixture, public dataset, or benchmark result."""


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _as_map(value: object, label: str) -> JsonMap:
    if isinstance(value, dict):
        return cast(JsonMap, value)
    raise BenchmarkError(f"{label} isn't an object")


def _as_list(value: object, label: str) -> list[object]:
    if isinstance(value, list):
        return value
    raise BenchmarkError(f"{label} isn't a list")


def _as_string(value: object, label: str) -> str:
    if isinstance(value, str):
        return value
    raise BenchmarkError(f"{label} isn't a string")


def _as_strings(value: object, label: str) -> list[str]:
    return [_as_string(item, f"{label} item") for item in _as_list(value, label)]


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _write_json(path: pathlib.Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_catalog() -> JsonMap:
    catalog = resources.files("mere_archive_tools").joinpath("benchmarks/sources.v1.json")
    return _as_map(json.loads(catalog.read_text(encoding="utf-8")), "benchmark source catalog")


def load_manifest(path: pathlib.Path) -> JsonMap:
    try:
        manifest = _as_map(json.loads(path.read_text(encoding="utf-8")), "benchmark manifest")
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"invalid benchmark manifest: {exc}") from None
    if manifest.get("contractVersion") != BENCHMARK_CONTRACT:
        raise BenchmarkError(f"unsupported benchmark contract in {path}")
    return manifest


def source_root(manifest_path: pathlib.Path, manifest: JsonMap) -> pathlib.Path:
    source = _as_map(manifest.get("source"), "benchmark source")
    raw_path = pathlib.Path(_as_string(source.get("path"), "benchmark source path"))
    resolved = raw_path if raw_path.is_absolute() else manifest_path.parent / raw_path
    return resolved.resolve()


def _zip_bytes(entries: Iterable[tuple[str, bytes]]) -> bytes:
    temporary = io.BytesIO()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    temporary.seek(0)
    return temporary.read()


def _docx(text: str) -> bytes:
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{html.escape(line)}</w:t></w:r></w:p>" for line in text.splitlines()
    )
    return _zip_bytes(
        [
            (
                "[Content_Types].xml",
                b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            ),
            (
                "_rels/.rels",
                b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
            ),
            (
                "word/document.xml",
                (f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{paragraphs}<w:sectPr/></w:body></w:document>').encode(),
            ),
        ]
    )


def _xlsx(rows: list[list[str]]) -> bytes:
    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(
            f'<c r="{chr(65 + column)}{row_index}" t="inlineStr"><is><t>{html.escape(value)}</t></is></c>'
            for column, value in enumerate(row)
        )
        row_xml.append(f'<row r="{row_index}">{cells}</row>')
    return _zip_bytes(
        [
            (
                "[Content_Types].xml",
                b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
            ),
            (
                "_rels/.rels",
                b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
            ),
            (
                "xl/workbook.xml",
                b'<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Audit" sheetId="1" r:id="rId1"/></sheets></workbook>',
            ),
            (
                "xl/_rels/workbook.xml.rels",
                b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
            ),
            (
                "xl/worksheets/sheet1.xml",
                (f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(row_xml)}</sheetData></worksheet>').encode(),
            ),
        ]
    )


def _pptx(title: str, body: str) -> bytes:
    slide = f"""<?xml version="1.0"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{html.escape(title)}</a:t></a:r></a:p><a:p><a:r><a:t>{html.escape(body)}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"""
    return _zip_bytes(
        [
            (
                "[Content_Types].xml",
                b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/><Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/></Types>',
            ),
            (
                "_rels/.rels",
                b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>',
            ),
            (
                "ppt/presentation.xml",
                b'<?xml version="1.0"?><p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/></p:presentation>',
            ),
            (
                "ppt/_rels/presentation.xml.rels",
                b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>',
            ),
            ("ppt/slides/slide1.xml", slide.encode()),
        ]
    )


def _epub(title: str, body: str) -> bytes:
    chapter = f'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>{html.escape(title)}</title></head><body><h1>{html.escape(title)}</h1><p>{html.escape(body)}</p></body></html>'
    return _zip_bytes(
        [
            ("mimetype", b"application/epub+zip"),
            (
                "META-INF/container.xml",
                b'<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
            ),
            (
                "OEBPS/content.opf",
                f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">mere-gauntlet</dc:identifier><dc:title>{html.escape(title)}</dc:title><dc:language>en</dc:language></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chapter"/></spine></package>'.encode(),
            ),
            ("OEBPS/chapter.xhtml", chapter.encode()),
        ]
    )


def _pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(content)


def _png(label: str, color: tuple[int, int, int]) -> bytes:
    width, height = 640, 360
    glyphs = {
        "0": ("111", "101", "101", "101", "111"),
        "1": ("010", "110", "010", "010", "111"),
        "2": ("111", "001", "111", "100", "111"),
        "4": ("101", "101", "111", "001", "001"),
        "A": ("010", "101", "111", "101", "101"),
        "B": ("110", "101", "110", "101", "110"),
        "D": ("110", "101", "101", "101", "110"),
        "E": ("111", "100", "110", "100", "111"),
        "F": ("111", "100", "110", "100", "100"),
        "H": ("101", "101", "111", "101", "101"),
        "L": ("100", "100", "100", "100", "111"),
        "M": ("10001", "11011", "10101", "10101", "10101"),
        "O": ("111", "101", "101", "101", "111"),
        "P": ("110", "101", "110", "100", "100"),
        "R": ("110", "101", "110", "101", "101"),
        "U": ("101", "101", "101", "101", "111"),
        "X": ("101", "101", "010", "101", "101"),
        "Y": ("101", "101", "010", "010", "010"),
    }
    pixels = bytearray((242, 242, 238) * width * height)

    def paint_rectangle(left: int, top: int, right: int, bottom: int, value: tuple[int, int, int]) -> None:
        for y_value in range(top, bottom):
            for x_value in range(left, right):
                offset = (y_value * width + x_value) * 3
                pixels[offset : offset + 3] = bytes(value)

    paint_rectangle(50, 80, 590, 280, color)
    paint_rectangle(62, 92, 578, 268, (255, 255, 255))
    scale = 7
    glyph_widths = [len(glyphs.get(character, ("",))[0]) if character != " " else 2 for character in label]
    text_width = sum((value + 1) * scale for value in glyph_widths) - scale
    cursor = (width - text_width) // 2
    top = 162
    for character, glyph_width in zip(label, glyph_widths):
        glyph = glyphs.get(character)
        if glyph is not None:
            for row_index, glyph_row in enumerate(glyph):
                for column_index, bit in enumerate(glyph_row):
                    if bit == "1":
                        paint_rectangle(
                            cursor + column_index * scale,
                            top + row_index * scale,
                            cursor + (column_index + 1) * scale,
                            top + (row_index + 1) * scale,
                            (24, 24, 24),
                        )
        cursor += (glyph_width + 1) * scale
    rows = []
    for y_value in range(height):
        scanline = bytearray([0])
        for x_value in range(width):
            offset = (y_value * width + x_value) * 3
            scanline.extend(pixels[offset : offset + 3])
        rows.append(bytes(scanline))
    raw = b"".join(rows)

    def chunk(name: bytes, value: bytes) -> bytes:
        return struct.pack(">I", len(value)) + name + value + struct.pack(">I", zlib.crc32(name + value))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"tEXt", b"Description\x00" + label.encode())
        + chunk(b"IDAT", zlib.compress(raw, level=9))
        + chunk(b"IEND", b"")
    )


def _synthetic_files() -> dict[str, bytes]:
    pump = (
        b"# Halifax blue pump installation\n\n"
        b"The facilities team installed asset PUMP-HFX-204 beside the north loading dock. "
        b"The casing is blue. Contact: dana@example.com. Telephone: 800-555-0199.\n"
    )
    return {
        "Operations/Halifax/2022/pump-installation.md": pump,
        "Old Backups/Halifax/pump-installation-copy.md": pump,
        "Operations/Calgary/2019/cold-storage-inspection.txt": (
            b"Calgary cold-storage inspection. The freezer alarm uses an amber beacon. "
            b"Corrective work order COLD-88 replaced the west evaporator fan."
        ),
        "Projects/Moncton/2024/solar-retrofit.json": json.dumps(
            {"project": "Moncton rooftop solar retrofit", "inverter": "SUN-47", "status": "commissioned"},
            sort_keys=True,
        ).encode(),
        "Safety/Dartmouth/2021/fire-door-audit.yaml": (
            b"site: Dartmouth fabrication shop\naudit: fire doors\nfinding: Door D-14 needs a new closer\n"
        ),
        "Maintenance/Yarmouth/2020/generator-service.xml": (
            b"<service><site>Yarmouth depot</site><asset>GEN-YAR-9</asset><work>starter battery replaced</work></service>"
        ),
        "Moves/Truro/2018/office-inventory.csv": (
            b"room,item,tag\nArchive,rolling cabinet,CAB-311\nReception,map case,MAP-72\n"
        ),
        "Leases/Sydney/2023/warehouse-terms.rtf": (
            b"{\\rtf1\\ansi Sydney warehouse lease. Bay seven is reserved for marine cable storage.}"
        ),
        "IT/Fredericton/2025/network-refresh.docx": _docx(
            "Fredericton network refresh\nSwitch stack NET-FRD-62 serves the second-floor training room."
        ),
        "Engineering/Saint John/2022/stormwater-plan.pdf": _pdf(
            "Saint John stormwater plan: inspect catch basin SJ-17 after heavy rain."
        ),
        "Access/Charlottetown/2024/accessibility-audit.xlsx": _xlsx(
            [["Site", "Finding", "Reference"], ["Charlottetown", "Ramp handrail clearance", "ACC-54"]]
        ),
        "Board/Bedford/2025/facilities-update.pptx": _pptx(
            "Bedford facilities update", "The board selected the cedar facade option for building BFD-6."
        ),
        "Manuals/Antigonish/2017/safety-handbook.epub": _epub(
            "Antigonish safety handbook", "The muster point is the east gravel lot beside marker ANT-3."
        ),
        "Photos/Halifax/2022/blue-pump-204.png": _png("BLUE PUMP HFX 204", (34, 88, 190)),
        "Photos/Dartmouth/2021/red-bay-door-12.png": _png("RED BAY DOOR 12", (194, 52, 45)),
        "Misc/2016/server-migration.log": b"2016-03-18 legacy server migration completed for rack LEGACY-2\n",
        "Meeting Notes/2020/regional-roundup.jsonl": (
            b'{"site":"Amherst","topic":"parking lot drainage","ticket":"AMH-31"}\n'
        ),
        "Policies/records-retention.rst": (
            b"Records retention\n=================\nDraft folders use the seven-year review marker RET-7.\n"
        ),
    }


def _synthetic_mutated_files() -> dict[str, bytes]:
    files = dict(_synthetic_files())
    files["Recovered/Halifax/pump-installation-copy.md"] = files.pop(
        "Old Backups/Halifax/pump-installation-copy.md"
    )
    files["Operations/Calgary/2019/cold-storage-inspection.txt"] += (
        b" Post-inspection update: the freezer alarm now uses violet beacon code ORBIT-73."
    )
    del files["Misc/2016/server-migration.log"]
    files["Incoming/2026/bridge-crane-inspection.txt"] = (
        b"Bridgewater crane inspection. Hoist CRANE-BRW-5 needs a new upper limit switch."
    )
    return files


def _source_files(files: dict[str, bytes]) -> list[JsonMap]:
    return [
        {"path": path, "sha256": _sha256_bytes(content), "sizeBytes": len(content)}
        for path, content in sorted(files.items())
    ]


def _source_file_records(source: pathlib.Path) -> list[JsonMap]:
    records = []
    for path in sorted(source.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in extractors.SUPPORTED_EXTENSIONS:
            records.append(
                {
                    "path": str(path.relative_to(source)),
                    "sha256": _sha256_file(path),
                    "sizeBytes": path.stat().st_size,
                }
            )
    return records


def _synthetic_documents(mutated: bool) -> list[JsonMap]:
    duplicate_path = (
        "Recovered/Halifax/pump-installation-copy.md"
        if mutated
        else "Old Backups/Halifax/pump-installation-copy.md"
    )
    documents: list[tuple[str, list[str]]] = [
        ("halifax-blue-pump", ["Operations/Halifax/2022/pump-installation.md", duplicate_path]),
        ("calgary-cold-storage", ["Operations/Calgary/2019/cold-storage-inspection.txt"]),
        ("moncton-solar", ["Projects/Moncton/2024/solar-retrofit.json"]),
        ("dartmouth-fire-door", ["Safety/Dartmouth/2021/fire-door-audit.yaml"]),
        ("yarmouth-generator", ["Maintenance/Yarmouth/2020/generator-service.xml"]),
        ("truro-inventory", ["Moves/Truro/2018/office-inventory.csv"]),
        ("sydney-lease", ["Leases/Sydney/2023/warehouse-terms.rtf"]),
        ("fredericton-network", ["IT/Fredericton/2025/network-refresh.docx"]),
        ("saint-john-stormwater", ["Engineering/Saint John/2022/stormwater-plan.pdf"]),
        ("charlottetown-accessibility", ["Access/Charlottetown/2024/accessibility-audit.xlsx"]),
        ("bedford-facilities", ["Board/Bedford/2025/facilities-update.pptx"]),
        ("antigonish-safety", ["Manuals/Antigonish/2017/safety-handbook.epub"]),
        ("halifax-pump-photo", ["Photos/Halifax/2022/blue-pump-204.png"]),
        ("dartmouth-door-photo", ["Photos/Dartmouth/2021/red-bay-door-12.png"]),
        ("amherst-drainage", ["Meeting Notes/2020/regional-roundup.jsonl"]),
        ("retention-policy", ["Policies/records-retention.rst"]),
    ]
    if mutated:
        documents.append(("bridgewater-crane", ["Incoming/2026/bridge-crane-inspection.txt"]))
    return [{"id": document_id, "paths": paths} for document_id, paths in documents]


def _synthetic_queries(mutated: bool) -> list[JsonMap]:
    queries = [
        ("q-blue-pump", "Which file describes the blue pump installed at the Halifax north loading dock?", "halifax-blue-pump"),
        ("q-cold-storage", "What record covers the Calgary freezer alarm and west evaporator fan?", "calgary-cold-storage"),
        ("q-solar", "Where is the Moncton SUN-47 rooftop inverter documented?", "moncton-solar"),
        ("q-fire-door", "Which Dartmouth fire door needs a new closer?", "dartmouth-fire-door"),
        ("q-generator", "Find the Yarmouth generator starter battery service record.", "yarmouth-generator"),
        ("q-inventory", "Which Truro office inventory lists the rolling cabinet?", "truro-inventory"),
        ("q-lease", "Where are the Sydney marine cable storage lease terms?", "sydney-lease"),
        ("q-network", "Find the Fredericton switch stack for the training room.", "fredericton-network"),
        ("q-stormwater", "Which Saint John catch basin needs inspection after heavy rain?", "saint-john-stormwater"),
        ("q-accessibility", "Find the Charlottetown ramp handrail clearance audit.", "charlottetown-accessibility"),
        ("q-board", "Which Bedford board update selected a cedar facade?", "bedford-facilities"),
        ("q-muster", "Where is the Antigonish muster point beside marker ANT-3?", "antigonish-safety"),
        ("q-pump-photo", "Find the photo of the blue Halifax pump marked 204.", "halifax-pump-photo"),
        ("q-door-photo", "Find the image of the red Dartmouth bay door marked 12.", "dartmouth-door-photo"),
        ("q-drainage", "Which Amherst note discusses parking lot drainage?", "amherst-drainage"),
        ("q-retention", "Which policy uses the RET-7 seven-year review marker?", "retention-policy"),
    ]
    if mutated:
        queries.extend(
            [
                ("q-orbit", "Which Calgary alarm now uses violet beacon code ORBIT-73?", "calgary-cold-storage"),
                ("q-crane", "Find the Bridgewater crane that needs an upper limit switch.", "bridgewater-crane"),
            ]
        )
    return [
        {"id": query_id, "text": text, "relevantDocumentIds": [document_id]}
        for query_id, text, document_id in queries
    ]


def _harbourline_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}

    def text(path: str, value: str) -> None:
        files[path] = value.encode()

    def pdf(path: str, value: str) -> None:
        files[path] = _pdf(value)

    def docx(path: str, value: str) -> None:
        files[path] = _docx(value)

    def xlsx(path: str, rows: list[list[str]]) -> None:
        files[path] = _xlsx(rows)

    def pptx(path: str, title: str, body: str) -> None:
        files[path] = _pptx(title, body)

    def image(path: str, asset: str) -> None:
        files[path] = resources.files("mere_archive_tools").joinpath(
            f"benchmarks/harbourline/{asset}"
        ).read_bytes()

    halifax_work_order = (
        "Harbourline Cold Storage - corrective work order WO-HFX-241842\n"
        "Site: Halifax North Dock. Asset: Freezer 3, evaporator EVAP-HFX-03.\n"
        "On 2024-02-17, the high-temperature alarm followed an iced west evaporator fan. "
        "Northshore Refrigeration replaced fan motor FM-8821 and defrost relay DR-44. "
        "Parts carry a 24-month warranty through 2026-02-17. "
        "Technician: Dana Mercer, dana@example.com, 800-555-0199."
    )
    pdf("Facilities/Halifax/Freezer 3/2024/WO-HFX-241842-corrective-repair.pdf", halifax_work_order)
    text("Facilities/Halifax/Freezer 3/2024/alarm-log.jsonl", '\n'.join([
        '{"time":"2024-02-17T05:51:00-04:00","asset":"EVAP-HFX-03","alarm":"high temperature","reading_c":-12.8}',
        '{"time":"2024-02-17T06:08:00-04:00","asset":"EVAP-HFX-03","observation":"west fan stalled; ice buildup visible"}',
        '{"time":"2024-02-17T11:42:00-04:00","asset":"EVAP-HFX-03","status":"returned to -21.0 C"}',
    ]))
    xlsx("Facilities/Halifax/Asset Registers/2025-freezer-assets.xlsx", [
        ["Asset", "Location", "Manufacturer", "Model", "Serial", "Critical spare"],
        ["EVAP-HFX-03", "Freezer 3 west wall", "Mariner Cooling", "MC-EV-480", "HFX3-24117", "FM-8821"],
        ["COMP-HFX-03A", "Freezer 3 plant room", "Mariner Cooling", "MC-COMP-90", "HFX90-1138", "seal kit SK-90"],
    ])
    pdf("Finance/Accounts Payable/Northshore Refrigeration/2024/INV-8841.pdf",
        "Invoice INV-8841. Harbourline Halifax. Work order WO-HFX-241842. "
        "Fan motor FM-8821: $1,840. Defrost relay DR-44: $320. Labour: $960. Total: $3,120. "
        "Warranty reference NSR-24M-8841. Contact dana@example.com, 800-555-0199.")
    docx("Vendors/Northshore Refrigeration/service-agreement-2024.docx",
         "Northshore Refrigeration service agreement. Emergency response target: four hours. "
         "Installed parts receive a 24-month warranty. Dispatch: dana@example.com, 800-555-0199.")
    text("Operations/Halifax/Shift Handover/2024-02-17.md",
         "# Halifax shift handover\nFreezer 3 returned to -21 C at 11:42. Northshore replaced the west fan motor and defrost relay. "
         "Verify temperature every two hours through 18 February. Product remained below the escalation threshold.")
    docx("Safety/Halifax/Incident Reviews/2024-02-freezer-3-review.docx",
         "Freezer 3 incident review. Root cause: drain pan ice obstructed the west evaporator fan. "
         "Action: add drain inspection to the January preventive-maintenance route. Owner: Facilities.")
    image("Facilities/Halifax/Freezer 3/2024/Photos/evaporator-west-ice.png", "freezer-evaporator-west-ice.png")
    image("Facilities/Halifax/Freezer 3/2024/Photos/nameplate-mc-ev-480.png", "freezer-nameplate.png")
    files["Old Backups/Email Attachments/2024/INV-8841-copy.pdf"] = files[
        "Finance/Accounts Payable/Northshore Refrigeration/2024/INV-8841.pdf"
    ]

    pdf("Safety/Dartmouth/Fire Doors/2025/Bay-12-inspection.pdf",
        "Harbourline Dartmouth Bay 12 fire-door inspection. Door FD-DAR-12 did not self-close. "
        "The hydraulic closer leaked and the pallet staging area obstructed the marked clearance zone. Corrective action due 2025-05-09.")
    text("Safety/Dartmouth/Fire Doors/2025/corrective-actions.csv",
         "action,owner,due,status\nReplace FD-DAR-12 closer,Facilities,2025-05-09,complete\nRepaint clearance zone,Operations,2025-05-09,complete\n")
    pdf("Procurement/Purchase Orders/2025/PO-5528-fire-door-closer.pdf",
        "Purchase order PO-5528. DoorSafe Atlantic. Norton 1601 closer for FD-DAR-12. Approved amount $685. Delivery 2025-05-06.")
    docx("Safety/Dartmouth/Fire Doors/2025/completion-signoff.docx",
         "Corrective action closeout for FD-DAR-12. New closer installed 2025-05-07. Door completed ten self-close tests. Clearance zone repainted and photographed.")
    image("Safety/Dartmouth/Fire Doors/2025/Photos/bay-12-before.png", "fire-door-before.png")
    image("Safety/Dartmouth/Fire Doors/2025/Photos/bay-12-complete.png", "fire-door-complete.png")

    pdf("Engineering/Saint John/Stormwater/2025/SJ-17-inspection.pdf",
        "Catch basin SJ-17 at the east truck entrance drains slowly after heavy rain. Sediment depth measured 28 cm. Cleanout recommended before 2025-09-30.")
    text("Operations/Saint John/Weather Events/2025-08-22.md",
         "Rainfall event: 71 mm in 24 hours. Ponding reached the east truck entrance near catch basin SJ-17. No building water entry.")
    xlsx("Engineering/Saint John/Stormwater/asset-register.xlsx", [
        ["Asset", "Location", "Last cleanout", "Risk"], ["SJ-17", "East truck entrance", "2023-10-12", "High"],
        ["SJ-09", "Employee parking", "2025-04-03", "Low"]])
    pdf("Procurement/Quotes/2025/Saint John/SJ-17-cleanout-quotes.pdf",
        "SJ-17 cleanout quotes. Bay Environmental: $2,480. Fundy Vac Services: $2,720. Scope includes sediment removal and disposal manifest.")
    image("Engineering/Saint John/Stormwater/Photos/SJ-17-after-rain.png", "catch-basin-after-rain.png")
    text("Meeting Notes/Regional Facilities/2025-08-28.jsonl",
         '{"site":"Saint John","decision":"approve Bay Environmental for SJ-17 cleanout","budget":"2480","owner":"Quinn"}\n')

    text("Projects/Moncton/Solar/2025/inverter-commissioning.json",
         json.dumps({"site":"Moncton", "asset":"SUN-47", "status":"commissioned", "date":"2025-06-18", "capacity_kw":125}, sort_keys=True))
    pdf("Projects/Moncton/Solar/2025/electrical-inspection.pdf",
        "Moncton rooftop solar electrical inspection. Inverter SUN-47 passed isolation, grounding, and shutdown tests on 2025-06-18.")
    xlsx("Projects/Moncton/Solar/2025/monthly-output.xlsx", [
        ["Month", "Expected kWh", "Actual kWh"], ["2025-07", "14800", "15120"], ["2025-08", "13700", "12940"]])
    pptx("Board/Capital Projects/2025-Q3-facilities.pptx", "Capital projects - Q3 2025",
         "Moncton solar commissioned. August output was 5.5% below plan; inspect rooftop array for shading and debris. Halifax Freezer 3 replacement remains in the 2027 plan.")
    image("Projects/Moncton/Solar/2025/Photos/rooftop-array-toolbox.png", "solar-rooftop-toolbox.png")
    docx("Projects/Moncton/Solar/2025/warranty.docx",
         "SUN-47 inverter warranty. Ten-year equipment coverage. Claim portal requires serial MCT-S47-8820 and commissioning report.")

    pdf("Maintenance/Yarmouth/Generator/2024/monthly-test-2024-11.pdf",
        "Generator GEN-YAR-9 monthly test. Starter battery voltage fell to 10.4 V under crank. Replace battery before the December test.")
    text("Maintenance/Yarmouth/Generator/2024/service-history.xml",
         "<history><asset>GEN-YAR-9</asset><service date='2024-11-21'>starter battery replaced; load test passed</service></history>")
    xlsx("Maintenance/Yarmouth/Generator/fuel-and-runtime.xlsx", [
        ["Date", "Runtime hours", "Fuel percent"], ["2024-11-21", "438", "82"], ["2025-02-20", "442", "76"]])
    image("Maintenance/Yarmouth/Generator/Photos/yellow-generator-panel.png", "yellow-generator-panel.png")
    pdf("Finance/Accounts Payable/Yarmouth Power/2024/battery-invoice.pdf",
        "Invoice for GEN-YAR-9 starter battery. Battery BAT-31HD, $486. Installed 2024-11-21. Warranty 36 months.")
    docx("Emergency Plans/Yarmouth/power-loss-procedure.docx",
         "Yarmouth power-loss procedure. Confirm GEN-YAR-9 starts, transfer switch closes, and cold rooms remain below limits. Record every manual start.")

    xlsx("Inventory/Truro/Material Handling/forklift-register.xlsx", [
        ["Asset", "Type", "Inspection due", "Assigned area"], ["FLT-TRU-07", "Electric forklift", "2025-10-03", "Freezer staging"],
        ["PJT-TRU-11", "Pallet jack", "2025-08-19", "Dry storage"]])
    pdf("Safety/Truro/Training/2025/forklift-certifications.pdf",
        "Truro forklift certifications. Operators Alex Chen and Noor Rahman certified for FLT-TRU-07 through 2026-04-30.")
    text("Inventory/Truro/Cycle Counts/2025-08.csv",
         "location,item,quantity\nA-14,purple tote,38\nB-02,fan motor FM-8821,1\nC-08,defrost relay DR-44,4\n")
    image("Inventory/Truro/Photos/aisle-a-blue-ladder.png", "warehouse-blue-ladder.png")
    docx("Operations/Truro/2025/aisle-safety-review.docx",
         "Aisle A safety review. Move the blue rolling ladder to the marked bay after use. Keep the yellow pallet jack clear of fire equipment.")
    files["Old Backups/Truro/2025-08-cycle-count-copy.csv"] = files["Inventory/Truro/Cycle Counts/2025-08.csv"]

    pdf("Leases/Sydney/2023/warehouse-lease.pdf",
        "Sydney overflow warehouse lease. Bay 7 is reserved for marine cable storage. Renewal notice due 2026-01-31. Annual rent $84,000.")
    docx("Leases/Sydney/2025/renewal-options.docx",
         "Sydney lease options. Three-year renewal at $89,500 annually or month-to-month at $8,600. Facilities recommends exiting after cable inventory falls below 12 reels.")
    xlsx("Inventory/Sydney/2025/marine-cable.xlsx", [
        ["Date", "Bay", "Reels"], ["2025-01-31", "7", "26"], ["2025-08-31", "7", "14"]])
    text("Meeting Notes/Sydney/2025-09-04.md",
         "Sydney lease review. Fourteen cable reels remain. Defer renewal decision until November forecast; notice deadline is 31 January 2026.")
    pdf("Finance/Sydney/2025/storage-cost-review.pdf",
        "Sydney storage cost review. Current annual lease cost is $84,000. Internal space becomes available after Halifax racking project in December 2025.")

    docx("IT/Fredericton/2025/network-refresh.docx",
         "Fredericton network refresh. Switch stack NET-FRD-62 serves the second-floor training room. Replacement window approved for 2025-11-08.")
    xlsx("IT/Asset Registers/network-equipment.xlsx", [
        ["Asset", "Site", "Model", "Support end"], ["NET-FRD-62", "Fredericton", "Summit 48P", "2025-12-31"],
        ["NET-HFX-11", "Halifax", "Summit 24P", "2027-06-30"]])
    pdf("Procurement/Purchase Orders/2025/PO-5610-network-refresh.pdf",
        "PO-5610. Replacement switch stack for Fredericton training room. Vendor: Atlantic Systems. Total $18,420. Delivery 2025-10-28.")
    text("IT/Change Calendar/2025-Q4.yaml",
         "changes:\n  - date: 2025-11-08\n    site: Fredericton\n    asset: NET-FRD-62\n    impact: training room network unavailable 08:00-12:00\n")
    pptx("IT/Steering Committee/2025-09-update.pptx", "Technology renewal",
         "Fredericton NET-FRD-62 reaches support end in December. Hardware is ordered under PO-5610. Change window: 8 November.")

    pdf("Compliance/2025/records-retention-policy.pdf",
        "Harbourline records retention policy. Maintenance and food-safety records use review marker RET-7. Access follows job role. Local indexes require an approved owner, encrypted storage, and tested backup.")
    docx("Compliance/2025/privacy-handling-guide.docx",
         "Privacy handling guide. Reduce contact details before creating search indexes. Source records remain authoritative and unchanged. Report suspected exposure to dana@example.com.")
    xlsx("Vendors/master-vendor-register.xlsx", [
        ["Vendor", "Service", "Email", "Phone"], ["Northshore Refrigeration", "Cooling", "dana@example.com", "800-555-0199"],
        ["Bay Environmental", "Drainage", "dana@example.com", "800-555-0199"]])
    pptx("Board/2026-capital-plan.pptx", "2026 capital priorities",
         "Priority one: replace Halifax Freezer 3 west evaporator and controls. Evidence: two corrective repairs since 2024 and parts-support risk after 2027.")
    text("Finance/Capital Planning/2026/facility-projects.csv",
         "project,site,budget,status\nFreezer 3 evaporator replacement,Halifax,185000,proposed\nSydney racking consolidation,Halifax,72000,approved\n")
    pdf("Insurance/2025/property-risk-survey.pdf",
        "Property risk survey. Halifax Freezer 3 is business-critical. Maintain tested spares for fan motor FM-8821 and relay DR-44 until planned replacement.")
    text("Archive/README.txt",
         "Harbourline shared-drive export. Files span Facilities, Operations, Safety, Finance, Procurement, IT, Compliance, and Board records. Originals are retained by the owning teams.")
    text("Archive/Unfiled/notes-from-old-laptop.log",
         "2019-06-07 replaced office printer toner. 2020-01-11 moved spare chairs. 2021-03-18 archived retired pager list.")
    return files


def _harbourline_documents() -> list[JsonMap]:
    groups = {
        "hfx-repair": ["Facilities/Halifax/Freezer 3/2024/WO-HFX-241842-corrective-repair.pdf"],
        "hfx-alarm": ["Facilities/Halifax/Freezer 3/2024/alarm-log.jsonl"],
        "hfx-assets": ["Facilities/Halifax/Asset Registers/2025-freezer-assets.xlsx"],
        "hfx-invoice": ["Finance/Accounts Payable/Northshore Refrigeration/2024/INV-8841.pdf", "Old Backups/Email Attachments/2024/INV-8841-copy.pdf"],
        "hfx-vendor": ["Vendors/Northshore Refrigeration/service-agreement-2024.docx"],
        "hfx-handover": ["Operations/Halifax/Shift Handover/2024-02-17.md"],
        "hfx-review": ["Safety/Halifax/Incident Reviews/2024-02-freezer-3-review.docx"],
        "hfx-ice-photo": ["Facilities/Halifax/Freezer 3/2024/Photos/evaporator-west-ice.png"],
        "hfx-nameplate-photo": ["Facilities/Halifax/Freezer 3/2024/Photos/nameplate-mc-ev-480.png"],
        "dar-inspection": ["Safety/Dartmouth/Fire Doors/2025/Bay-12-inspection.pdf"],
        "dar-actions": ["Safety/Dartmouth/Fire Doors/2025/corrective-actions.csv"],
        "dar-po": ["Procurement/Purchase Orders/2025/PO-5528-fire-door-closer.pdf"],
        "dar-closeout": ["Safety/Dartmouth/Fire Doors/2025/completion-signoff.docx"],
        "dar-before-photo": ["Safety/Dartmouth/Fire Doors/2025/Photos/bay-12-before.png"],
        "dar-after-photo": ["Safety/Dartmouth/Fire Doors/2025/Photos/bay-12-complete.png"],
        "sj-inspection": ["Engineering/Saint John/Stormwater/2025/SJ-17-inspection.pdf"],
        "sj-rain": ["Operations/Saint John/Weather Events/2025-08-22.md"],
        "sj-assets": ["Engineering/Saint John/Stormwater/asset-register.xlsx"],
        "sj-quotes": ["Procurement/Quotes/2025/Saint John/SJ-17-cleanout-quotes.pdf"],
        "sj-photo": ["Engineering/Saint John/Stormwater/Photos/SJ-17-after-rain.png"],
        "sj-decision": ["Meeting Notes/Regional Facilities/2025-08-28.jsonl"],
        "mct-commissioning": ["Projects/Moncton/Solar/2025/inverter-commissioning.json"],
        "mct-inspection": ["Projects/Moncton/Solar/2025/electrical-inspection.pdf"],
        "mct-output": ["Projects/Moncton/Solar/2025/monthly-output.xlsx"],
        "mct-board": ["Board/Capital Projects/2025-Q3-facilities.pptx"],
        "mct-photo": ["Projects/Moncton/Solar/2025/Photos/rooftop-array-toolbox.png"],
        "mct-warranty": ["Projects/Moncton/Solar/2025/warranty.docx"],
        "yar-test": ["Maintenance/Yarmouth/Generator/2024/monthly-test-2024-11.pdf"],
        "yar-history": ["Maintenance/Yarmouth/Generator/2024/service-history.xml"],
        "yar-runtime": ["Maintenance/Yarmouth/Generator/fuel-and-runtime.xlsx"],
        "yar-photo": ["Maintenance/Yarmouth/Generator/Photos/yellow-generator-panel.png"],
        "yar-invoice": ["Finance/Accounts Payable/Yarmouth Power/2024/battery-invoice.pdf"],
        "yar-procedure": ["Emergency Plans/Yarmouth/power-loss-procedure.docx"],
        "tru-register": ["Inventory/Truro/Material Handling/forklift-register.xlsx"],
        "tru-training": ["Safety/Truro/Training/2025/forklift-certifications.pdf"],
        "tru-count": ["Inventory/Truro/Cycle Counts/2025-08.csv", "Old Backups/Truro/2025-08-cycle-count-copy.csv"],
        "tru-photo": ["Inventory/Truro/Photos/aisle-a-blue-ladder.png"],
        "tru-safety": ["Operations/Truro/2025/aisle-safety-review.docx"],
        "syd-lease": ["Leases/Sydney/2023/warehouse-lease.pdf"],
        "syd-options": ["Leases/Sydney/2025/renewal-options.docx"],
        "syd-inventory": ["Inventory/Sydney/2025/marine-cable.xlsx"],
        "syd-notes": ["Meeting Notes/Sydney/2025-09-04.md"],
        "syd-cost": ["Finance/Sydney/2025/storage-cost-review.pdf"],
        "frd-refresh": ["IT/Fredericton/2025/network-refresh.docx"],
        "frd-register": ["IT/Asset Registers/network-equipment.xlsx"],
        "frd-po": ["Procurement/Purchase Orders/2025/PO-5610-network-refresh.pdf"],
        "frd-calendar": ["IT/Change Calendar/2025-Q4.yaml"],
        "frd-board": ["IT/Steering Committee/2025-09-update.pptx"],
        "policy-retention": ["Compliance/2025/records-retention-policy.pdf"],
        "policy-privacy": ["Compliance/2025/privacy-handling-guide.docx"],
        "vendor-register": ["Vendors/master-vendor-register.xlsx"],
        "capital-board": ["Board/2026-capital-plan.pptx"],
        "capital-projects": ["Finance/Capital Planning/2026/facility-projects.csv"],
        "insurance-risk": ["Insurance/2025/property-risk-survey.pdf"],
        "archive-readme": ["Archive/README.txt"],
        "archive-noise": ["Archive/Unfiled/notes-from-old-laptop.log"],
    }
    return [{"id": document_id, "paths": paths} for document_id, paths in groups.items()]


def _harbourline_queries() -> list[JsonMap]:
    questions = [
        ("hfx-response", "What failed on Halifax Freezer 3, which parts were installed, and when does their warranty end?", ["hfx-repair", "hfx-invoice", "hfx-vendor"]),
        ("hfx-dispatch", "Give the service history, equipment model, and photo evidence for Halifax Freezer 3 before dispatching a technician.", ["hfx-repair", "hfx-assets", "hfx-ice-photo", "hfx-nameplate-photo"]),
        ("hfx-root-cause", "What caused the 2024 Halifax Freezer 3 incident and what preventive action was added?", ["hfx-review", "hfx-alarm"]),
        ("hfx-spares", "Which critical spares should Halifax keep for Freezer 3?", ["hfx-assets", "insurance-risk"]),
        ("hfx-cost", "How much did the 2024 Freezer 3 repair cost and which work order supports it?", ["hfx-invoice", "hfx-repair"]),
        ("hfx-recovery", "When did Freezer 3 return to temperature and what monitoring followed?", ["hfx-alarm", "hfx-handover"]),
        ("dar-finding", "What was wrong with Dartmouth Bay 12 fire door?", ["dar-inspection", "dar-before-photo"]),
        ("dar-proof", "Show the inspection, repair order, closeout, and completion photo for Dartmouth fire door FD-DAR-12.", ["dar-inspection", "dar-po", "dar-closeout", "dar-after-photo"]),
        ("dar-status", "Were the Dartmouth Bay 12 corrective actions completed by the due date?", ["dar-actions", "dar-closeout"]),
        ("sj-response", "Why does Saint John catch basin SJ-17 need work, and which contractor was approved?", ["sj-inspection", "sj-rain", "sj-decision"]),
        ("sj-cost", "Compare the Saint John SJ-17 cleanout quotes and find the approved amount.", ["sj-quotes", "sj-decision"]),
        ("sj-evidence", "Find the post-rain photo and inspection for the east truck entrance catch basin.", ["sj-photo", "sj-inspection"]),
        ("mct-performance", "Why was Moncton solar output below plan in August, and what should Facilities inspect?", ["mct-output", "mct-board", "mct-photo"]),
        ("mct-warranty", "Find the commissioning evidence and warranty for Moncton inverter SUN-47.", ["mct-commissioning", "mct-inspection", "mct-warranty"]),
        ("yar-battery", "Why was the Yarmouth generator battery replaced, and what warranty applies?", ["yar-test", "yar-history", "yar-invoice"]),
        ("yar-readiness", "Find the Yarmouth emergency power procedure, latest runtime record, and generator photo.", ["yar-procedure", "yar-runtime", "yar-photo"]),
        ("tru-spare", "Does Truro have a spare fan motor for Halifax Freezer 3?", ["tru-count", "hfx-assets"]),
        ("tru-safety", "Find the forklift training record and aisle safety issue at Truro.", ["tru-training", "tru-safety", "tru-photo"]),
        ("syd-decision", "Should Harbourline renew the Sydney warehouse now, and what facts remain unresolved?", ["syd-lease", "syd-options", "syd-inventory", "syd-notes", "syd-cost"]),
        ("syd-deadline", "When is the Sydney lease notice deadline and how many cable reels remained in August?", ["syd-lease", "syd-inventory"]),
        ("frd-change", "When will Fredericton switch NET-FRD-62 be replaced and who supplies the hardware?", ["frd-refresh", "frd-po", "frd-calendar"]),
        ("frd-risk", "Why must Fredericton replace NET-FRD-62 before year end?", ["frd-register", "frd-board"]),
        ("capital-case", "What evidence supports replacing Halifax Freezer 3 in the capital plan?", ["capital-board", "capital-projects", "hfx-repair", "hfx-review", "insurance-risk"]),
        ("retention", "What controls apply before Harbourline builds a local records index?", ["policy-retention", "policy-privacy"]),
        ("vendor-contact", "Find Northshore Refrigeration's service terms without exposing the contact details in the retained index.", ["hfx-vendor", "vendor-register", "policy-privacy"]),
        ("duplicate-invoice", "Find every path containing Northshore invoice INV-8841.", ["hfx-invoice"]),
        ("duplicate-count", "Find every path for the Truro cycle count that lists one spare fan motor FM-8821.", ["tru-count"]),
        ("cross-site-parts", "Which sites have records for fan motor FM-8821?", ["hfx-repair", "hfx-assets", "hfx-invoice", "tru-count", "insurance-risk"]),
        ("board-overview", "Which current facilities issues appear in board materials?", ["mct-board", "capital-board"]),
        ("source-authority", "Which file explains who owns the original Harbourline records?", ["archive-readme"]),
    ]
    return [
        {"id": query_id, "text": query, "relevantDocumentIds": relevant}
        for query_id, query, relevant in questions
    ]


def _harbourline_phase(files: dict[str, bytes]) -> JsonMap:
    return {
        "sourceFiles": _source_files(files),
        "documents": _harbourline_documents(),
        "queries": _harbourline_queries(),
        "duplicateGroups": [
            {
                "id": "northshore-invoice-copy",
                "paths": ["Finance/Accounts Payable/Northshore Refrigeration/2024/INV-8841.pdf", "Old Backups/Email Attachments/2024/INV-8841-copy.pdf"],
            },
            {
                "id": "truro-cycle-count-copy",
                "paths": ["Inventory/Truro/Cycle Counts/2025-08.csv", "Old Backups/Truro/2025-08-cycle-count-copy.csv"],
            },
        ],
        "requireNoFileErrors": True,
    }


def _phase(files: dict[str, bytes], mutated: bool, require_no_errors: bool = True) -> JsonMap:
    duplicate_path = (
        "Recovered/Halifax/pump-installation-copy.md"
        if mutated
        else "Old Backups/Halifax/pump-installation-copy.md"
    )
    return {
        "sourceFiles": _source_files(files),
        "documents": _synthetic_documents(mutated),
        "queries": _synthetic_queries(mutated),
        "duplicateGroups": [
            {
                "id": "halifax-pump-copy",
                "paths": ["Operations/Halifax/2022/pump-installation.md", duplicate_path],
            }
        ],
        "requireNoFileErrors": require_no_errors,
    }


def _manifest(dataset: JsonMap, phases: JsonMap, canaries: list[str], provenance: JsonMap) -> JsonMap:
    return {
        "contractVersion": BENCHMARK_CONTRACT,
        "createdAt": _now_iso(),
        "dataset": dataset,
        "source": {"path": "source", "accessDuringIndex": "read-only"},
        "privacyCanaries": canaries,
        "phases": phases,
        "provenance": provenance,
    }


def _prepare_directory(output_dir: pathlib.Path) -> pathlib.Path:
    if output_dir.exists():
        raise BenchmarkError(f"benchmark output already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    return pathlib.Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))


def prepare_synthetic(output_dir: pathlib.Path) -> JsonMap:
    staging = _prepare_directory(output_dir)
    try:
        source = staging / "source"
        baseline = _synthetic_files()
        for relative_path, content in baseline.items():
            destination = source / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        manifest = _manifest(
            {
                "id": SYNTHETIC_DATASET_ID,
                "name": "Mere Archive Gauntlet",
                "license": "MIT",
                "redistribution": "included as generated test data",
            },
            {
                "baseline": _phase(baseline, False),
                "mutated": _phase(_synthetic_mutated_files(), True),
            },
            ["dana@example.com", "800-555-0199"],
            {"generator": "mere-archive-tools", "networkUsed": False},
        )
        manifest["mutations"] = [
            {
                "operation": "move",
                "source": "Old Backups/Halifax/pump-installation-copy.md",
                "destination": "Recovered/Halifax/pump-installation-copy.md",
            },
            {
                "operation": "appendText",
                "path": "Operations/Calgary/2019/cold-storage-inspection.txt",
                "text": " Post-inspection update: the freezer alarm now uses violet beacon code ORBIT-73.",
            },
            {"operation": "delete", "path": "Misc/2016/server-migration.log"},
            {
                "operation": "writeText",
                "path": "Incoming/2026/bridge-crane-inspection.txt",
                "text": "Bridgewater crane inspection. Hoist CRANE-BRW-5 needs a new upper limit switch.",
            },
        ]
        _write_json(staging / "benchmark.json", manifest)
        _write_json(staging / "state.json", {"contractVersion": BENCHMARK_CONTRACT, "phase": "baseline"})
        staging.replace(output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return load_manifest(output_dir / "benchmark.json")


def prepare_harbourline(output_dir: pathlib.Path) -> JsonMap:
    staging = _prepare_directory(output_dir)
    try:
        source = staging / "source"
        baseline = _harbourline_files()
        for relative_path, content in baseline.items():
            destination = source / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        manifest = _manifest(
            {
                "id": HARBOURLINE_DATASET_ID,
                "name": "Harbourline Cold Storage Operations Archive",
                "license": "MIT",
                "redistribution": "included as generated fictional test data",
            },
            {"baseline": _harbourline_phase(baseline)},
            ["dana@example.com", "800-555-0199"],
            {
                "generator": "mere-archive-tools",
                "networkUsed": False,
                "company": "Harbourline Cold Storage",
                "fictional": True,
            },
        )
        _write_json(staging / "benchmark.json", manifest)
        _write_json(staging / "state.json", {"contractVersion": BENCHMARK_CONTRACT, "phase": "baseline"})
        staging.replace(output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return load_manifest(output_dir / "benchmark.json")


def _request_json(url: str) -> JsonMap:
    request = urllib.request.Request(url, headers={"User-Agent": "mere-archive-tools/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return _as_map(json.loads(response.read()), f"response from {url}")


def _download(url: str, destination: pathlib.Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "mere-archive-tools/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def prepare_vidore(output_dir: pathlib.Path, limit: int) -> JsonMap:
    if not 1 <= limit <= 1_000:
        raise BenchmarkError("ViDoRe --limit must be between 1 and 1000")
    catalog = source_catalog()
    datasets = _as_map(catalog.get("datasets"), "benchmark datasets")
    recipe = _as_map(datasets.get(VIDORE_DATASET_ID), VIDORE_DATASET_ID)
    revision = _as_string(recipe.get("revision"), "ViDoRe revision")
    staging = _prepare_directory(output_dir)
    try:
        source = staging / "source"
        source.mkdir()
        documents: dict[str, JsonMap] = {}
        query_documents: dict[str, set[str]] = {}
        query_order: list[str] = []
        for offset in range(0, limit, 100):
            length = min(100, limit - offset)
            query = urllib.parse.urlencode(
                {
                    "dataset": "vidore/syntheticDocQA_government_reports_test",
                    "config": "default",
                    "split": "test",
                    "offset": offset,
                    "length": length,
                    "revision": revision,
                }
            )
            payload = _request_json(f"{VIDORE_ROWS_URL}?{query}")
            for raw_item in _as_list(payload.get("rows"), "ViDoRe rows"):
                item = _as_map(raw_item, "ViDoRe row")
                row = _as_map(item.get("row"), "ViDoRe row data")
                original_name = _as_string(row.get("image_filename"), "ViDoRe image filename")
                query_text = _as_string(row.get("query"), "ViDoRe query")
                document_id = "doc-" + hashlib.sha256(original_name.encode()).hexdigest()[:16]
                if document_id not in documents:
                    image = _as_map(row.get("image"), "ViDoRe image")
                    image_url = _as_string(image.get("src"), "ViDoRe image URL")
                    local_path = f"pages/{document_id}.jpg"
                    destination = source / local_path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    _download(image_url, destination)
                    documents[document_id] = {
                        "id": document_id,
                        "paths": [local_path],
                        "originalPath": original_name,
                    }
                if query_text not in query_documents:
                    query_documents[query_text] = set()
                    query_order.append(query_text)
                query_documents[query_text].add(document_id)
        queries = [
            {
                "id": f"q-{index:04d}",
                "text": query_text,
                "relevantDocumentIds": sorted(query_documents[query_text]),
            }
            for index, query_text in enumerate(query_order, start=1)
        ]
        phase = {
            "sourceFiles": _source_file_records(source),
            "documents": sorted(documents.values(), key=lambda item: str(item["id"])),
            "queries": queries,
            "duplicateGroups": [],
            "requireNoFileErrors": True,
        }
        manifest = _manifest(
            {
                "id": VIDORE_DATASET_ID,
                "name": "ViDoRe syntheticDocQA government reports",
                "license": recipe.get("license"),
                "redistribution": "download on demand; not bundled",
                "selectedRows": limit,
            },
            {"baseline": phase},
            [],
            {
                "homepage": recipe.get("homepage"),
                "revision": revision,
                "parquetSha256": recipe.get("parquetSha256"),
                "rowService": VIDORE_ROWS_URL,
                "networkUsed": True,
            },
        )
        _write_json(staging / "benchmark.json", manifest)
        _write_json(staging / "state.json", {"contractVersion": BENCHMARK_CONTRACT, "phase": "baseline"})
        staging.replace(output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return load_manifest(output_dir / "benchmark.json")


def _safe_extract(archive_path: pathlib.Path, destination: pathlib.Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            relative = pathlib.PurePosixPath(member.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise BenchmarkError(f"archive contains an unsafe path: {member.filename}")
            if member.is_dir() or pathlib.Path(member.filename).suffix.lower() not in extractors.SUPPORTED_EXTENSIONS:
                continue
            mode = member.external_attr >> 16
            if mode & 0o170000 == 0o120000:
                raise BenchmarkError(f"archive contains a symbolic link: {member.filename}")
            output = destination.joinpath(*relative.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, output.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)


def prepare_govdocs(output_dir: pathlib.Path) -> JsonMap:
    catalog = source_catalog()
    datasets = _as_map(catalog.get("datasets"), "benchmark datasets")
    recipe = _as_map(datasets.get(GOVDOCS_DATASET_ID), GOVDOCS_DATASET_ID)
    archive_url = _as_string(recipe.get("archiveUrl"), "GovDocs1 archive URL")
    expected_sha1 = _as_string(recipe.get("archiveSha1"), "GovDocs1 archive checksum")
    staging = _prepare_directory(output_dir)
    try:
        archive_path = staging / "govdocs1-000.zip"
        _download(archive_url, archive_path)
        digest = hashlib.sha1()
        with archive_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        archive_sha1 = digest.hexdigest()
        if archive_sha1 != expected_sha1:
            raise BenchmarkError(f"GovDocs1 shard checksum mismatch: {archive_sha1}")
        source = staging / "source"
        source.mkdir()
        _safe_extract(archive_path, source)
        archive_path.unlink()
        source_files = _source_file_records(source)
        documents = [
            {"id": "doc-" + hashlib.sha256(path.encode()).hexdigest()[:16], "paths": [path]}
            for path in sorted(_as_string(item.get("path"), "source file path") for item in source_files)
        ]
        phase = {
            "sourceFiles": source_files,
            "documents": documents,
            "queries": [],
            "duplicateGroups": [],
            "requireNoFileErrors": False,
        }
        manifest = _manifest(
            {
                "id": GOVDOCS_DATASET_ID,
                "name": "GovDocs1 shard 000",
                "license": recipe.get("license"),
                "redistribution": "download on demand; review source terms",
            },
            {"baseline": phase},
            [],
            {
                "homepage": recipe.get("homepage"),
                "archive": archive_url,
                "archiveSha1": expected_sha1,
                "networkUsed": True,
            },
        )
        _write_json(staging / "benchmark.json", manifest)
        _write_json(staging / "state.json", {"contractVersion": BENCHMARK_CONTRACT, "phase": "baseline"})
        staging.replace(output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return load_manifest(output_dir / "benchmark.json")


def prepare(dataset_id: str, output_dir: pathlib.Path, limit: int) -> JsonMap:
    if dataset_id == SYNTHETIC_DATASET_ID:
        return prepare_synthetic(output_dir)
    if dataset_id == HARBOURLINE_DATASET_ID:
        return prepare_harbourline(output_dir)
    if dataset_id == VIDORE_DATASET_ID:
        return prepare_vidore(output_dir, limit)
    if dataset_id == GOVDOCS_DATASET_ID:
        return prepare_govdocs(output_dir)
    raise BenchmarkError(f"unknown benchmark dataset: {dataset_id}")


def _phase_files(phase: JsonMap) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_item in _as_list(phase.get("sourceFiles"), "benchmark source files"):
        item = _as_map(raw_item, "benchmark source file")
        values[_as_string(item.get("path"), "source file path")] = _as_string(
            item.get("sha256"), "source file checksum"
        )
    return values


def _current_files(source: pathlib.Path) -> dict[str, str]:
    return {
        str(path.relative_to(source)): _sha256_file(path)
        for path in sorted(source.rglob("*"))
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in extractors.SUPPORTED_EXTENSIONS
    }


def detect_phase(manifest: JsonMap, source: pathlib.Path) -> tuple[str, JsonMap, bool]:
    phases = _as_map(manifest.get("phases"), "benchmark phases")
    current = _current_files(source)
    for name, raw_phase in phases.items():
        phase = _as_map(raw_phase, f"benchmark phase {name}")
        if _phase_files(phase) == current:
            return name, phase, True
    baseline = _as_map(phases.get("baseline"), "benchmark baseline phase")
    return "unknown", baseline, False


def mutate(manifest_path: pathlib.Path) -> JsonMap:
    manifest = load_manifest(manifest_path)
    dataset = _as_map(manifest.get("dataset"), "benchmark dataset")
    if dataset.get("id") != SYNTHETIC_DATASET_ID:
        raise BenchmarkError("mutations are available only for the generated Mere Archive Gauntlet")
    source = source_root(manifest_path, manifest)
    if source != (manifest_path.parent / "source").resolve():
        raise BenchmarkError("the generated benchmark source must be beside its manifest")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise BenchmarkError("the generated benchmark source contains a symbolic link")

    def confined_path(value: object, label: str) -> pathlib.Path:
        path = (source / _as_string(value, label)).resolve()
        try:
            path.relative_to(source)
        except ValueError:
            raise BenchmarkError(f"{label} escapes the generated benchmark source") from None
        return path

    phase_name, _, exact = detect_phase(manifest, source)
    if not exact or phase_name != "baseline":
        raise BenchmarkError("the generated source doesn't match the baseline phase")
    for raw_operation in _as_list(manifest.get("mutations"), "benchmark mutations"):
        operation = _as_map(raw_operation, "benchmark mutation")
        kind = _as_string(operation.get("operation"), "mutation operation")
        if kind == "move":
            origin = confined_path(operation.get("source"), "move source")
            destination = confined_path(operation.get("destination"), "move destination")
            destination.parent.mkdir(parents=True, exist_ok=True)
            origin.replace(destination)
        elif kind == "appendText":
            path = confined_path(operation.get("path"), "append path")
            path.write_text(path.read_text(encoding="utf-8") + _as_string(operation.get("text"), "append text"))
        elif kind == "delete":
            confined_path(operation.get("path"), "delete path").unlink()
        elif kind == "writeText":
            path = confined_path(operation.get("path"), "write path")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_as_string(operation.get("text"), "write text"), encoding="utf-8")
        else:
            raise BenchmarkError(f"unsupported benchmark mutation: {kind}")
    phase_name, phase, exact = detect_phase(manifest, source)
    if not exact or phase_name != "mutated":
        raise BenchmarkError("the mutation result doesn't match the expected phase")
    state = {"contractVersion": BENCHMARK_CONTRACT, "phase": phase_name, "updatedAt": _now_iso()}
    _write_json(manifest_path.parent / "state.json", state)
    return {**state, "source": str(source), "sourceFiles": len(_phase_files(phase))}


def _check(name: str, passed: bool, detail: object) -> JsonMap:
    return {"name": name, "passed": passed, "detail": detail}


def _tier_check(connection: sqlite3.Connection, tier: str) -> JsonMap:
    contents = int(connection.execute("SELECT COUNT(*) FROM contents").fetchone()[0])
    bad_pii = int(connection.execute("SELECT COUNT(*) FROM contents WHERE pii_reduced != 1").fetchone()[0])
    display_missing = int(
        connection.execute("SELECT COUNT(*) FROM contents WHERE display_text IS NULL OR display_text = ''").fetchone()[0]
    )
    keyword_missing = int(connection.execute("SELECT COUNT(*) FROM contents WHERE keywords_json IS NULL").fetchone()[0])
    retained_chunks = int(connection.execute("SELECT COUNT(*) FROM chunks WHERE text IS NOT NULL").fetchone()[0])
    text_chunks = int(connection.execute("SELECT COUNT(*) FROM chunks WHERE modality = 'text'").fetchone()[0])
    fts_rows = int(connection.execute("SELECT COUNT(*) FROM content_fts").fetchone()[0])
    if tier == "full-content":
        passed = bad_pii == 0 and display_missing == 0 and retained_chunks == text_chunks and fts_rows == contents
    elif tier == "safe-content":
        passed = bad_pii == 0 and display_missing == 0 and keyword_missing == 0 and retained_chunks == 0 and fts_rows == contents
    elif tier == "pointers":
        display_rows = contents - display_missing
        keyword_rows = contents - keyword_missing
        passed = bad_pii == 0 and display_rows == 0 and keyword_rows == 0 and retained_chunks == 0 and fts_rows == 0
    else:
        passed = False
    return _check(
        "storage-tier-invariants",
        passed,
        {
            "tier": tier,
            "contents": contents,
            "displayMissing": display_missing,
            "keywordMissing": keyword_missing,
            "retainedChunkText": retained_chunks,
            "textChunks": text_chunks,
            "fullTextRecords": fts_rows,
            "invalidPiiFlags": bad_pii,
        },
    )


def _privacy_check(connection: sqlite3.Connection, database_path: pathlib.Path, canaries: list[str]) -> JsonMap:
    values: list[str] = []
    for query in (
        "SELECT display_text FROM contents WHERE display_text IS NOT NULL",
        "SELECT keywords_json FROM contents WHERE keywords_json IS NOT NULL",
        "SELECT text FROM chunks WHERE text IS NOT NULL",
        "SELECT body FROM content_fts",
    ):
        values.extend(str(row[0]) for row in connection.execute(query))
    combined = "\n".join(values).casefold()
    logical_leaks = sorted(canary for canary in canaries if canary.casefold() in combined)
    byte_leaks: set[str] = set()
    for path in (database_path, pathlib.Path(str(database_path) + "-wal"), pathlib.Path(str(database_path) + "-shm")):
        if not path.is_file():
            continue
        value = path.read_bytes().lower()
        byte_leaks.update(canary for canary in canaries if canary.lower().encode() in value)
    leaks = sorted(set(logical_leaks) | byte_leaks)
    return _check(
        "exact-pii-canary-scan",
        not leaks,
        {"canaryCount": len(canaries), "leaks": leaks, "scope": "retained SQLite text and database bytes"},
    )


def _retrieved_document_groups(results: list[object], path_to_document: dict[str, str]) -> list[set[str]]:
    groups: list[set[str]] = []
    for raw_result in results:
        result = _as_map(raw_result, "search result")
        result_ids: set[str] = set()
        for raw_path in _as_list(result.get("paths"), "search result paths"):
            path = _as_map(raw_path, "search result path")
            relative_path = _as_string(path.get("relativePath"), "search result relative path")
            document_id = path_to_document.get(relative_path)
            if document_id is not None:
                result_ids.add(document_id)
        groups.append(result_ids)
    return groups


def _retrieval_metrics(phase: JsonMap, search: SearchFunction, top: int) -> JsonMap:
    path_to_document: dict[str, str] = {}
    for raw_document in _as_list(phase.get("documents"), "benchmark documents"):
        document = _as_map(raw_document, "benchmark document")
        identifier = _as_string(document.get("id"), "document id")
        for path in _as_strings(document.get("paths"), "document paths"):
            path_to_document[path] = identifier
    details: list[JsonMap] = []
    recalls: dict[int, list[float]] = {1: [], 5: [], 10: []}
    hits: dict[int, list[float]] = {1: [], 5: [], 10: []}
    reciprocal_ranks: list[float] = []
    latencies_ms: list[float] = []
    queries = _as_list(phase.get("queries"), "benchmark queries")
    for raw_query in queries:
        query = _as_map(raw_query, "benchmark query")
        query_id = _as_string(query.get("id"), "query id")
        query_text = _as_string(query.get("text"), "query text")
        relevant = set(_as_strings(query.get("relevantDocumentIds"), "relevant document ids"))
        started = time.perf_counter()
        payload = search(query_text, top)
        latencies_ms.append((time.perf_counter() - started) * 1_000)
        retrieved = _retrieved_document_groups(_as_list(payload.get("results"), "search results"), path_to_document)
        for cutoff in recalls:
            retrieved_ids: set[str] = set()
            for values in retrieved[:cutoff]:
                retrieved_ids.update(values)
            found = relevant.intersection(retrieved_ids)
            recalls[cutoff].append(len(found) / len(relevant) if relevant else 0.0)
            hits[cutoff].append(1.0 if found else 0.0)
        first_rank = next(
            (index for index, values in enumerate(retrieved[:10], start=1) if values.intersection(relevant)),
            None,
        )
        reciprocal_ranks.append(1.0 / first_rank if first_rank is not None else 0.0)
        details.append(
            {
                "id": query_id,
                "relevantDocumentIds": sorted(relevant),
                "retrievedResults": [
                    {"rank": rank, "documentIds": sorted(values)}
                    for rank, values in enumerate(retrieved[:10], start=1)
                ],
                "firstRelevantRank": first_rank,
            }
        )
    count = len(queries)
    def average(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    ordered_latencies = sorted(latencies_ms)
    p50_index = max(0, (len(ordered_latencies) - 1) // 2)
    p95_index = max(0, (len(ordered_latencies) * 95 + 99) // 100 - 1)
    latency = {
        "mean": round(average(latencies_ms) or 0.0, 3) if latencies_ms else None,
        "p50": round(ordered_latencies[p50_index], 3) if latencies_ms else None,
        "p95": round(ordered_latencies[p95_index], 3) if latencies_ms else None,
        "maximum": round(ordered_latencies[-1], 3) if latencies_ms else None,
    }
    return {
        "scored": bool(queries),
        "queryCount": count,
        "recallAt1": average(recalls[1]),
        "recallAt5": average(recalls[5]),
        "recallAt10": average(recalls[10]),
        "hitRateAt1": average(hits[1]),
        "hitRateAt5": average(hits[5]),
        "hitRateAt10": average(hits[10]),
        "mrrAt10": average(reciprocal_ranks),
        "searchLatencyMs": latency,
        "queries": details,
    }


def evaluate(
    manifest_path: pathlib.Path,
    database_path: pathlib.Path,
    search: SearchFunction,
    top: int,
    minimum_recall_at_5: float | None,
    minimum_mrr_at_10: float | None,
) -> JsonMap:
    manifest = load_manifest(manifest_path)
    source = source_root(manifest_path, manifest)
    phase_name, phase, source_exact = detect_phase(manifest, source)
    expected_paths = set(_phase_files(phase))
    checks = [_check("source-integrity", source_exact, {"phase": phase_name, "files": len(expected_paths)})]
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        metadata = {
            str(row["key"]): str(row["value"])
            for row in connection.execute("SELECT key, value FROM metadata")
        }
        tier = metadata.get("storage_tier", "")
        checks.append(
            _check(
                "source-root-binding",
                pathlib.Path(metadata.get("source_root", "")).resolve() == source,
                {"expected": str(source), "database": metadata.get("source_root")},
            )
        )
        rows = connection.execute("SELECT relative_path, status, content_id FROM files").fetchall()
        database_paths = {str(row["relative_path"]) for row in rows}
        missing = sorted(expected_paths - database_paths)
        stale = sorted(database_paths - expected_paths)
        complete = {str(row["relative_path"]) for row in rows if row["status"] == "complete"}
        errors = sorted(str(row["relative_path"]) for row in rows if row["status"] == "error")
        require_no_errors = bool(phase.get("requireNoFileErrors", True))
        checks.append(
            _check(
                "index-coverage",
                not missing
                and not stale
                and bool(complete)
                and (not errors or not require_no_errors),
                {
                    "expected": len(expected_paths),
                    "complete": len(complete),
                    "successfulCoverage": len(complete) / len(expected_paths) if expected_paths else 0.0,
                    "errors": errors,
                    "missing": missing,
                    "stale": stale,
                    "requiresNoErrors": require_no_errors,
                },
            )
        )
        duplicate_failures: list[str] = []
        content_by_path = {
            str(row["relative_path"]): int(row["content_id"])
            for row in rows
            if row["status"] == "complete" and row["content_id"] is not None
        }
        for raw_group in _as_list(phase.get("duplicateGroups"), "duplicate groups"):
            group = _as_map(raw_group, "duplicate group")
            paths = _as_strings(group.get("paths"), "duplicate paths")
            identifiers = {content_by_path.get(path) for path in paths}
            if None in identifiers or len(identifiers) != 1:
                duplicate_failures.append(_as_string(group.get("id"), "duplicate group id"))
        checks.append(_check("content-deduplication", not duplicate_failures, {"failures": duplicate_failures}))
        checks.append(_tier_check(connection, tier))
        canaries = _as_strings(manifest.get("privacyCanaries"), "privacy canaries")
        checks.append(_privacy_check(connection, database_path, canaries))
    except sqlite3.Error as exc:
        raise BenchmarkError(f"invalid archive database: {exc}") from None
    finally:
        connection.close()
    retrieval = _retrieval_metrics(phase, search, top)
    threshold_checks: list[JsonMap] = []
    for name, minimum, metric_name in (
        ("minimum-recall-at-5", minimum_recall_at_5, "recallAt5"),
        ("minimum-mrr-at-10", minimum_mrr_at_10, "mrrAt10"),
    ):
        if minimum is None:
            continue
        value = retrieval.get(metric_name)
        passed = isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) >= minimum
        threshold_checks.append(_check(name, passed, {"minimum": minimum, "actual": value}))
    checks.extend(threshold_checks)
    passed = all(bool(check["passed"]) for check in checks)
    dataset = _as_map(manifest.get("dataset"), "benchmark dataset")
    return {
        "contractVersion": REPORT_CONTRACT,
        "createdAt": _now_iso(),
        "passed": passed,
        "dataset": {"id": dataset.get("id"), "name": dataset.get("name")},
        "phase": phase_name,
        "database": str(database_path),
        "databaseSizeBytes": database_path.stat().st_size,
        "checks": checks,
        "retrieval": retrieval,
    }
