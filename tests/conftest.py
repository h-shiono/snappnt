import pytest


def pytest_collection_modifyitems(config, items):
    """Skip ``slow`` tests unless the marker expression names them (``pytest -m slow``)."""
    if "slow" in (config.getoption("markexpr") or ""):
        return
    skip = pytest.mark.skip(reason="slow: run with pytest -m slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
