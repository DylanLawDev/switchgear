"""Shared validation and resolution for locally stored artifacts."""

from pathlib import Path


def is_safe_artifact_filename(filename: str) -> bool:
    candidate = Path(filename)
    return (
        bool(filename)
        and candidate.name == filename
        and ".." not in filename
        and "\\" not in filename
    )


def resolve_artifact_path(root: Path, filename: str) -> Path:
    if not is_safe_artifact_filename(filename):
        raise ValueError("invalid artifact filename")
    resolved_root = root.resolve()
    candidate = (resolved_root / filename).resolve()
    if candidate.parent != resolved_root:
        raise ValueError("artifact path escapes its storage directory")
    return candidate
