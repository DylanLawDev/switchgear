from pathlib import Path

import pytest

from switchgear.artifacts import is_safe_artifact_filename, resolve_artifact_path


def test_resolve_artifact_path_keeps_basename_under_root(tmp_path):
    assert resolve_artifact_path(tmp_path, "resume.pdf") == (tmp_path / "resume.pdf").resolve()


@pytest.mark.parametrize("filename", ["", ".", "..", "../secret", "nested/file"])
def test_resolve_artifact_path_rejects_non_basename(filename):
    with pytest.raises(ValueError):
        resolve_artifact_path(Path("artifacts"), filename)


@pytest.mark.parametrize("filename", ["resume.pdf", "shot1.png", "a.b.c"])
def test_is_safe_artifact_filename_accepts_plain_basenames(filename):
    assert is_safe_artifact_filename(filename) is True


@pytest.mark.parametrize(
    "filename",
    [
        "",
        ".",
        "..",
        "..foo",
        "foo..",
        "..evil",
        "../secret",
        "nested/file",
        "nested\\file",
        "\\windows\\path",
    ],
)
def test_is_safe_artifact_filename_rejects_traversal_and_separators(filename):
    assert is_safe_artifact_filename(filename) is False
