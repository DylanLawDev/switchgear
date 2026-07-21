import pytest

from switchgear.web import spa


@pytest.fixture(autouse=True)
def _isolated_spa_static_dir(tmp_path, monkeypatch):
    """Make tests hermetic to whether a built SPA exists on disk.

    ``spa.STATIC_DIR`` is read at call time (see spa.spa_index()), so tests
    that don't opt into a fake SPA build should behave the same whether or
    not a developer has actually run the frontend build (which lands at
    src/switchgear/web/static/app/index.html and is gitignored). Point it at a
    fresh, empty tmp_path by default; tests that want a "with SPA" world
    (e.g. tests/test_spa_serving.py's fake_spa fixture) monkeypatch it again
    to a directory containing index.html.
    """
    monkeypatch.setattr(spa, "STATIC_DIR", tmp_path / "no-spa-static")
