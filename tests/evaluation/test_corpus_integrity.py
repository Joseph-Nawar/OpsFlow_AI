from pathlib import Path

from opsflow.documents.models import DocumentInput
from opsflow.documents.processor import process_document
from opsflow.evaluation.corpus import load_manifest, resolve_manifest_source


def test_production_document_processor_preserves_all_manifest_source_identity_and_truth() -> None:
    corpus_root = Path("evals/corpus/v1")
    manifest = load_manifest(corpus_root)

    for case in manifest.cases:
        source_path = resolve_manifest_source(corpus_root, case.source.path)
        content = source_path.read_bytes()
        canonical = process_document(
            DocumentInput(
                document_type=case.source.document_type,
                name=source_path.name,
                mime_type=case.source.mime_type,
                content=content,
                source_reference=case.source.path,
            )
        )

        assert canonical.sha256 == case.source.sha256, case.case_id
        assert canonical.document_type is case.source.document_type, case.case_id
        assert canonical.mime_type == case.source.mime_type, case.case_id

        expected = case.expected_extraction
        if expected is None:
            continue
        searchable = "\n".join(
            [
                canonical.text,
                *(page.text for page in canonical.pages),
                *(cell for table in canonical.tables for row in table.rows for cell in row),
            ]
        )
        assert expected.po_number is None or expected.po_number in searchable, case.case_id
        assert expected.customer_reference is None or expected.customer_reference in searchable, (
            case.case_id
        )
        for line in expected.lines:
            assert line.sku is None or line.sku in searchable, case.case_id
