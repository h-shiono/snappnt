def test_failed_write_leaves_no_temporary_files(tmp_path, monkeypatch):
    import numpy as np
    import pytest

    from snappnt.io import sigmf_io

    def fail(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(sigmf_io.Path, "write_text", fail)
    with pytest.raises(OSError):
        sigmf_io.write_sigmf(tmp_path / "x", np.zeros(8, np.complex64), 1e6)
    assert list(tmp_path.iterdir()) == []
