"""Manifest and source-integrity helpers for the synthetic evaluation corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from .models import CorpusManifest


def resolve_manifest_source(corpus_root: Path, source_path: str) -> Path:
    """Resolve one manifest path while preventing traversal and symlink escape."""

    if "\\" in source_path or "\x00" in source_path:
        raise ValueError("source path must use safe relative POSIX syntax")
    relative = PurePosixPath(source_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("source path must be relative to the corpus root")

    root = corpus_root.resolve()
    candidate = (root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("source path escapes the corpus root") from error
    return candidate


def verify_source_sha256(source_path: Path, expected_sha256: str) -> None:
    """Verify committed source bytes against the manifest's lowercase SHA-256."""

    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha256
    ):
        raise ValueError("expected_sha256 must be a lowercase 64-character SHA-256 digest")
    if not source_path.is_file():
        raise ValueError("manifest source file is missing")

    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ValueError("manifest source SHA-256 does not match committed bytes")


def load_manifest(corpus_root: Path) -> CorpusManifest:
    """Load and validate a corpus manifest plus every declared source digest."""

    manifest_path = corpus_root / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = CorpusManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ValueError("invalid evaluation corpus manifest") from error

    for case in manifest.cases:
        source_path = resolve_manifest_source(corpus_root, case.source.path)
        verify_source_sha256(source_path, case.source.sha256)
    return manifest


__all__ = ["load_manifest", "resolve_manifest_source", "verify_source_sha256"]
