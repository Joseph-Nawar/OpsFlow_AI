from __future__ import annotations

import io
import struct
import warnings
from collections.abc import Iterable
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from opsflow.documents import xlsx
from opsflow.documents.errors import (
    DocumentLimitError,
    DocumentParseError,
    DocumentValidationError,
)
from opsflow.documents.limits import DEFAULT_DOCUMENT_LIMITS, DocumentLimits

OOXML_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OOXML_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
WORKSHEET_REL = f"{OOXML_REL}/worksheet"


def _limits(**overrides: int) -> DocumentLimits:
    from dataclasses import replace

    return replace(DEFAULT_DOCUMENT_LIMITS, **overrides)


def _sheet_xml(cells: str = "") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="{OOXML_MAIN}">
  <dimension ref="A1:XFD1048576"/>
  <sheetData>{cells}</sheetData>
</worksheet>""".encode()


def _cell(coordinate: str, value: str, *, formula: str | None = None) -> str:
    formula_xml = f"<f>{formula}</f>" if formula is not None else ""
    row_number = coordinate.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return f'<row r="{row_number}"><c r="{coordinate}">{formula_xml}<v>{value}</v></c></row>'


def _workbook_xml(sheet_count: int) -> bytes:
    sheets = "".join(
        f'<sheet name="Sheet{index}" sheetId="{index}" r:id="rId{index}"/>'
        for index in range(1, sheet_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="{OOXML_MAIN}" xmlns:r="{OOXML_REL}">
  <sheets>{sheets}</sheets>
</workbook>""".encode()


def _relationships_xml(sheet_count: int) -> bytes:
    relationships = "".join(
        f'<Relationship Id="rId{index}" Type="{WORKSHEET_REL}" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{PACKAGE_REL}">{relationships}</Relationships>""".encode()


def _content_types_xml(sheet_count: int, *, extra: str = "") -> bytes:
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml"
            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  {overrides}{extra}
</Types>""".encode()


def _valid_entries(
    *,
    sheet_contents: Iterable[bytes] = (_sheet_xml(),),
    workbook: bytes | None = None,
    relationships: bytes | None = None,
    content_types: bytes | None = None,
) -> list[tuple[str, bytes]]:
    sheets = list(sheet_contents)
    return [
        (
            "[Content_Types].xml",
            content_types or _content_types_xml(len(sheets)),
        ),
        ("xl/workbook.xml", workbook or _workbook_xml(len(sheets))),
        (
            "xl/_rels/workbook.xml.rels",
            relationships or _relationships_xml(len(sheets)),
        ),
        *[
            (f"xl/worksheets/sheet{index}.xml", content)
            for index, content in enumerate(sheets, start=1)
        ],
    ]


def _zip_bytes(entries: Iterable[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            for name, content in entries:
                archive.writestr(name, content)
    return output.getvalue()


def _inflate_first_member_size(content: bytes, size: int) -> bytes:
    archive = bytearray(content)
    central_directory_signature = b"PK\x01\x02"
    offset = archive.find(central_directory_signature)
    assert offset >= 0
    struct.pack_into("<I", archive, offset + 24, size)
    return bytes(archive)


def test_xlsx_package_requires_content_types_and_workbook_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xlsx, "load_workbook", lambda *_args, **_kwargs: pytest.fail())

    for missing in ("[Content_Types].xml", "xl/workbook.xml"):
        entries = [entry for entry in _valid_entries() if entry[0] != missing]

        with pytest.raises(DocumentValidationError):
            xlsx._validate_xlsx_package(_zip_bytes(entries), DEFAULT_DOCUMENT_LIMITS)


def test_xlsx_package_rejects_non_zip_and_malformed_zip() -> None:
    valid = _zip_bytes(_valid_entries())

    with pytest.raises((DocumentParseError, DocumentValidationError)):
        xlsx._validate_xlsx_package(b"not a ZIP archive", DEFAULT_DOCUMENT_LIMITS)
    with pytest.raises((DocumentParseError, DocumentValidationError)):
        xlsx._validate_xlsx_package(valid[:-8], DEFAULT_DOCUMENT_LIMITS)


def test_xlsx_package_rejects_missing_or_malformed_relationship_metadata() -> None:
    missing = [entry for entry in _valid_entries() if entry[0] != "xl/_rels/workbook.xml.rels"]
    malformed = _valid_entries(relationships=b"<Relationships")

    with pytest.raises(DocumentValidationError):
        xlsx._validate_xlsx_package(_zip_bytes(missing), DEFAULT_DOCUMENT_LIMITS)
    with pytest.raises(DocumentValidationError):
        xlsx._validate_xlsx_package(_zip_bytes(malformed), DEFAULT_DOCUMENT_LIMITS)


def test_xlsx_package_rejects_duplicate_member_names() -> None:
    entries = _valid_entries()
    entries.append(("xl/workbook.xml", b"duplicate"))

    with pytest.raises(DocumentValidationError, match="duplicate"):
        xlsx._validate_xlsx_package(_zip_bytes(entries), DEFAULT_DOCUMENT_LIMITS)


def test_xlsx_package_rejects_macro_member_and_macro_content_type() -> None:
    macro_member = _valid_entries()
    macro_member.append(("xl/vbaProject.bin", b"macro bytes"))
    macro_type = _valid_entries(
        content_types=_content_types_xml(
            1,
            extra=(
                '<Override PartName="/xl/vbaProject.bin" '
                'ContentType="application/vnd.ms-office.vbaProject"/>'
            ),
        )
    )

    with pytest.raises(DocumentValidationError, match="macro"):
        xlsx._validate_xlsx_package(_zip_bytes(macro_member), DEFAULT_DOCUMENT_LIMITS)
    with pytest.raises(DocumentValidationError, match="macro"):
        xlsx._validate_xlsx_package(_zip_bytes(macro_type), DEFAULT_DOCUMENT_LIMITS)


def test_xlsx_package_enforces_expanded_size_before_workbook_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _inflate_first_member_size(_zip_bytes(_valid_entries()), 101)
    monkeypatch.setattr(xlsx, "load_workbook", lambda *_args, **_kwargs: pytest.fail())

    with pytest.raises(DocumentLimitError, match="expanded"):
        xlsx._validate_xlsx_package(
            content,
            _limits(max_xlsx_expanded_bytes=100),
        )


def test_xlsx_package_rejects_sheet_count_before_workbook_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = _valid_entries(sheet_contents=(_sheet_xml(), _sheet_xml()))
    monkeypatch.setattr(xlsx, "load_workbook", lambda *_args, **_kwargs: pytest.fail())

    with pytest.raises(DocumentLimitError, match="sheet"):
        xlsx._validate_xlsx_package(_zip_bytes(entries), _limits(max_xlsx_sheets=1))


def test_xlsx_package_sparse_row_guard_rejects_row_beyond_small_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _zip_bytes(_valid_entries(sheet_contents=(_sheet_xml(_cell("A6", "1")),)))
    monkeypatch.setattr(xlsx, "load_workbook", lambda *_args, **_kwargs: pytest.fail())

    with pytest.raises(DocumentLimitError, match="row"):
        xlsx._validate_xlsx_package(
            content,
            _limits(max_xlsx_rows_per_sheet=5),
        )


def test_xlsx_package_sparse_column_guard_rejects_column_beyond_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _zip_bytes(_valid_entries(sheet_contents=(_sheet_xml(_cell("C1", "1")),)))
    monkeypatch.setattr(xlsx, "load_workbook", lambda *_args, **_kwargs: pytest.fail())

    with pytest.raises(DocumentLimitError, match="column"):
        xlsx._validate_xlsx_package(
            content,
            _limits(max_table_columns=2),
        )


def test_xlsx_package_rejects_aggregate_populated_cell_limit() -> None:
    content = _zip_bytes(
        _valid_entries(sheet_contents=(_sheet_xml(_cell("A1", "1") + _cell("B1", "2")),))
    )

    with pytest.raises(DocumentLimitError, match="populated"):
        xlsx._validate_xlsx_package(
            content,
            _limits(max_xlsx_populated_cells=1),
        )


def test_xlsx_package_style_only_cells_do_not_expand_meaningful_bounds() -> None:
    style_only = '<row r="100"><c r="XFD100" s="1"/></row>'
    content = _zip_bytes(_valid_entries(sheet_contents=(_sheet_xml(style_only),)))

    package = xlsx._validate_xlsx_package(content, DEFAULT_DOCUMENT_LIMITS)

    assert package.populated_cell_count == 0
    assert package.sheets[0].max_meaningful_row == 0
    assert package.sheets[0].max_meaningful_column == 0


def test_xlsx_package_rejects_worksheet_relationship_outside_allowed_parts() -> None:
    relationships = _relationships_xml(1).replace(
        b'Target="worksheets/sheet1.xml"', b'Target="../external.xml"'
    )
    content = _zip_bytes(_valid_entries(relationships=relationships))

    with pytest.raises(DocumentValidationError, match="worksheet"):
        xlsx._validate_xlsx_package(content, DEFAULT_DOCUMENT_LIMITS)


def test_xlsx_package_rejects_malformed_cell_coordinate_safely() -> None:
    content = _zip_bytes(_valid_entries(sheet_contents=(_sheet_xml(_cell("A0", "1")),)))

    with pytest.raises(DocumentValidationError, match="coordinate"):
        xlsx._validate_xlsx_package(content, DEFAULT_DOCUMENT_LIMITS)
