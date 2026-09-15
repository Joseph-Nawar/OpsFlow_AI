"""Bounded XLSX package inspection and deterministic worksheet parsing."""

from __future__ import annotations

import io
import posixpath
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook  # type: ignore[import-untyped]  # noqa: F401

from opsflow.documents.errors import (
    DocumentLimitError,
    DocumentParseError,
    DocumentValidationError,
)
from opsflow.documents.limits import DocumentLimits

_OOXML_MAIN_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OOXML_RELATIONSHIP_NAMESPACE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
_PACKAGE_RELATIONSHIP_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
_WORKSHEET_RELATIONSHIP = f"{_OOXML_RELATIONSHIP_NAMESPACE}/worksheet"
_WORKBOOK_PART = "xl/workbook.xml"
_WORKBOOK_RELATIONSHIPS_PART = "xl/_rels/workbook.xml.rels"
_CONTENT_TYPES_PART = "[Content_Types].xml"
_WORKSHEET_PREFIX = "xl/worksheets/"
_CELL_COORDINATE = re.compile(r"([A-Za-z]{1,3})([1-9][0-9]*)$")
_MAX_XLSX_ROW = 1_048_576
_MAX_XLSX_COLUMN = 16_384


@dataclass(frozen=True, slots=True)
class _XlsxSheetBounds:
    """Preflight-bounded information for one worksheet package part."""

    title: str
    part_name: str
    max_meaningful_row: int
    max_meaningful_column: int


@dataclass(frozen=True, slots=True)
class _XlsxPackageInfo:
    """Private package metadata produced before openpyxl is invoked."""

    sheets: tuple[_XlsxSheetBounds, ...]
    populated_cell_count: int


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _required_member(names: set[str], member: str) -> None:
    if member not in names:
        raise DocumentValidationError(f"XLSX package is missing {member}")


def _read_member(archive: ZipFile, member: str) -> bytes:
    try:
        return archive.read(member)
    except (BadZipFile, KeyError, OSError) as exc:
        raise DocumentParseError("XLSX package member could not be read") from exc


def _validate_content_types(content: bytes) -> None:
    try:
        for _event, element in ElementTree.iterparse(
            io.BytesIO(content), events=("end",)
        ):
            if _local_name(element.tag) in {"Default", "Override"}:
                content_type = element.attrib.get("ContentType", "").lower()
                if "vba" in content_type or "macro" in content_type:
                    raise DocumentValidationError(
                        "XLSX package contains macro-bearing content"
                    )
            element.clear()
    except DocumentValidationError:
        raise
    except ElementTree.ParseError as exc:
        raise DocumentValidationError("XLSX content types metadata is malformed") from exc


def _read_workbook_sheets(content: bytes) -> list[tuple[str, str]]:
    sheets: list[tuple[str, str]] = []
    relationship_attribute = f"{{{_OOXML_RELATIONSHIP_NAMESPACE}}}id"
    try:
        for _event, element in ElementTree.iterparse(
            io.BytesIO(content), events=("end",)
        ):
            if _local_name(element.tag) == "sheet":
                title = element.attrib.get("name", "")
                relationship_id = element.attrib.get(relationship_attribute, "")
                if not title.strip() or not relationship_id.strip():
                    raise DocumentValidationError(
                        "XLSX workbook sheet metadata is incomplete"
                    )
                sheets.append((title, relationship_id))
            element.clear()
    except DocumentValidationError:
        raise
    except ElementTree.ParseError as exc:
        raise DocumentValidationError("XLSX workbook metadata is malformed") from exc
    if not sheets:
        raise DocumentValidationError("XLSX workbook contains no worksheets")
    return sheets


def _read_relationships(content: bytes) -> dict[str, tuple[str, str]]:
    relationships: dict[str, tuple[str, str]] = {}
    try:
        for _event, element in ElementTree.iterparse(
            io.BytesIO(content), events=("end",)
        ):
            if _local_name(element.tag) == "Relationship":
                relationship_id = element.attrib.get("Id", "")
                relationship_type = element.attrib.get("Type", "")
                target = element.attrib.get("Target", "")
                target_mode = element.attrib.get("TargetMode", "")
                if (
                    not relationship_id.strip()
                    or not relationship_type.strip()
                    or not target.strip()
                ):
                    raise DocumentValidationError(
                        "XLSX workbook relationship metadata is incomplete"
                    )
                if relationship_id in relationships:
                    raise DocumentValidationError(
                        "XLSX workbook relationship IDs are duplicated"
                    )
                if target_mode.lower() == "external":
                    raise DocumentValidationError(
                        "XLSX workbook has an external worksheet relationship"
                    )
                relationships[relationship_id] = (relationship_type, target)
            element.clear()
    except DocumentValidationError:
        raise
    except ElementTree.ParseError as exc:
        raise DocumentValidationError(
            "XLSX workbook relationship metadata is malformed"
        ) from exc
    return relationships


def _resolve_worksheet_part(target: str, names: set[str]) -> str:
    target_parts = target.replace("\\", "/").split("/")
    if ".." in target_parts:
        raise DocumentValidationError("XLSX worksheet relationship escapes its package")
    if target.startswith("/"):
        part_name = posixpath.normpath(target.lstrip("/"))
    else:
        part_name = posixpath.normpath(posixpath.join("xl", target))
    if not part_name.startswith(_WORKSHEET_PREFIX) or part_name == _WORKSHEET_PREFIX:
        raise DocumentValidationError("XLSX worksheet relationship has an invalid target")
    if part_name not in names:
        raise DocumentValidationError("XLSX worksheet relationship target is missing")
    return part_name


def _column_number(column_name: str) -> int:
    number = 0
    for character in column_name.upper():
        number = number * 26 + ord(character) - ord("A") + 1
    if number > _MAX_XLSX_COLUMN:
        raise DocumentValidationError("XLSX cell coordinate has an impossible column")
    return number


def _parse_coordinate(coordinate: str) -> tuple[int, int]:
    match = _CELL_COORDINATE.fullmatch(coordinate)
    if match is None:
        raise DocumentValidationError("XLSX cell coordinate is malformed")
    column = _column_number(match.group(1))
    row = int(match.group(2))
    if row > _MAX_XLSX_ROW:
        raise DocumentValidationError("XLSX cell coordinate has an impossible row")
    return row, column


def _scan_worksheet(
    archive: ZipFile,
    part_name: str,
    limits: DocumentLimits,
    remaining_populated_cells: int,
) -> tuple[int, int, int]:
    max_row = 0
    max_column = 0
    populated_cell_count = 0
    row_position = 0
    current_row = 0

    try:
        with archive.open(part_name) as stream:
            for event, element in ElementTree.iterparse(
                stream, events=("start", "end")
            ):
                element_name = _local_name(element.tag)
                if event == "start" and element_name == "row":
                    row_position += 1
                    row_value = element.attrib.get("r")
                    current_row = (
                        int(row_value)
                        if row_value is not None and row_value.isdigit()
                        else row_position
                    )
                    if current_row < 1 or current_row > _MAX_XLSX_ROW:
                        raise DocumentValidationError("XLSX row coordinate is impossible")
                elif event == "end" and element_name == "c":
                    meaningful = any(
                        _local_name(child.tag) in {"f", "v", "is"}
                        for child in element
                    )
                    if meaningful:
                        coordinate = element.attrib.get("r")
                        if coordinate is None:
                            raise DocumentValidationError(
                                "XLSX meaningful cell has no coordinate"
                            )
                        row, column = _parse_coordinate(coordinate)
                        if row > limits.max_xlsx_rows_per_sheet:
                            raise DocumentLimitError(
                                "XLSX row-span limit exceeded"
                            )
                        if column > limits.max_table_columns:
                            raise DocumentLimitError(
                                "XLSX table column limit exceeded"
                            )
                        populated_cell_count += 1
                        if populated_cell_count > remaining_populated_cells:
                            raise DocumentLimitError(
                                "XLSX populated-cell limit exceeded"
                            )
                        max_row = max(max_row, row)
                        max_column = max(max_column, column)
                if event == "end":
                    element.clear()
    except (DocumentLimitError, DocumentValidationError):
        raise
    except (BadZipFile, OSError, ElementTree.ParseError) as exc:
        raise DocumentParseError("XLSX worksheet XML is malformed") from exc

    return max_row, max_column, populated_cell_count


def _validate_xlsx_package(
    content: bytes,
    limits: DocumentLimits,
) -> _XlsxPackageInfo:
    """Validate package structure and scan bounded worksheet coordinates."""
    if not isinstance(content, bytes):
        raise DocumentValidationError("XLSX content must be bytes")

    try:
        with ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            names_in_order = [info.filename for info in infos]
            names = set(names_in_order)
            if len(names) != len(names_in_order):
                raise DocumentValidationError("XLSX package contains duplicate members")
            for name in names_in_order:
                if "vba" in name.lower() or name.lower().endswith("/vbaproject.bin"):
                    raise DocumentValidationError(
                        "XLSX package contains macro-bearing members"
                    )
            expanded_size = sum(info.file_size for info in infos)
            if expanded_size > limits.max_xlsx_expanded_bytes:
                raise DocumentLimitError("XLSX expanded-size limit exceeded")

            _required_member(names, _CONTENT_TYPES_PART)
            _required_member(names, _WORKBOOK_PART)
            _required_member(names, _WORKBOOK_RELATIONSHIPS_PART)
            _validate_content_types(_read_member(archive, _CONTENT_TYPES_PART))
            workbook_sheets = _read_workbook_sheets(_read_member(archive, _WORKBOOK_PART))
            if len(workbook_sheets) > limits.max_xlsx_sheets:
                raise DocumentLimitError("XLSX sheet limit exceeded")
            relationships = _read_relationships(
                _read_member(archive, _WORKBOOK_RELATIONSHIPS_PART)
            )

            sheet_bounds: list[_XlsxSheetBounds] = []
            total_populated_cells = 0
            for title, relationship_id in workbook_sheets:
                relationship = relationships.get(relationship_id)
                if relationship is None:
                    raise DocumentValidationError(
                        "XLSX worksheet relationship is missing"
                    )
                relationship_type, target = relationship
                if relationship_type != _WORKSHEET_RELATIONSHIP:
                    raise DocumentValidationError(
                        "XLSX worksheet relationship has an invalid type"
                    )
                part_name = _resolve_worksheet_part(target, names)
                max_row, max_column, populated = _scan_worksheet(
                    archive,
                    part_name,
                    limits,
                    limits.max_xlsx_populated_cells - total_populated_cells,
                )
                total_populated_cells += populated
                sheet_bounds.append(
                    _XlsxSheetBounds(
                        title=title,
                        part_name=part_name,
                        max_meaningful_row=max_row,
                        max_meaningful_column=max_column,
                    )
                )
            return _XlsxPackageInfo(
                sheets=tuple(sheet_bounds),
                populated_cell_count=total_populated_cells,
            )
    except (DocumentLimitError, DocumentValidationError, DocumentParseError):
        raise
    except (BadZipFile, OSError, ValueError) as exc:
        raise DocumentParseError("XLSX archive is invalid or unreadable") from exc
