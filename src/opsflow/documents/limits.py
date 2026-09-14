"""Resource limits for deterministic document processing."""

from dataclasses import dataclass

from opsflow.documents.errors import DocumentValidationError


def _require_positive_integer(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DocumentValidationError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class DocumentLimits:
    """Configured resource limits for one document-processing operation."""

    max_input_bytes: int
    max_text_characters: int
    max_pdf_pages: int
    max_xlsx_sheets: int
    max_xlsx_rows_per_sheet: int
    max_xlsx_populated_cells: int
    max_csv_rows: int
    max_table_columns: int
    max_xlsx_expanded_bytes: int

    def __post_init__(self) -> None:
        for name in (
            "max_input_bytes",
            "max_text_characters",
            "max_pdf_pages",
            "max_xlsx_sheets",
            "max_xlsx_rows_per_sheet",
            "max_xlsx_populated_cells",
            "max_csv_rows",
            "max_table_columns",
            "max_xlsx_expanded_bytes",
        ):
            _require_positive_integer(name, getattr(self, name))


DEFAULT_DOCUMENT_LIMITS = DocumentLimits(
    max_input_bytes=10 * 1024 * 1024,
    max_text_characters=1_000_000,
    max_pdf_pages=50,
    max_xlsx_sheets=20,
    max_xlsx_rows_per_sheet=5_000,
    max_xlsx_populated_cells=20_000,
    max_csv_rows=5_000,
    max_table_columns=100,
    max_xlsx_expanded_bytes=50 * 1024 * 1024,
)
