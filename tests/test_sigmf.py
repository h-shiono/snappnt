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


def _old_recording(tmp_path):
    import numpy as np

    from snappnt.io import sigmf_io

    old = (np.arange(8) + 1j * np.arange(8)).astype(np.complex64)
    sigmf_io.write_sigmf(tmp_path / "x", old, 1e6, description="old")
    return old, sorted(p.name for p in tmp_path.iterdir())


def _fail_nth_replace(monkeypatch, n, *, from_n_on=False):
    from snappnt.io import sigmf_io

    real = sigmf_io.Path.replace
    calls = []

    def replace(self, target):
        calls.append(self.name)
        if len(calls) == n or (from_n_on and len(calls) > n):
            raise OSError("rename failed")
        return real(self, target)

    monkeypatch.setattr(sigmf_io.Path, "replace", replace)


def test_replace_succeeds_and_leaves_only_new_files(tmp_path):
    import numpy as np

    from snappnt.io import sigmf_io

    _, names = _old_recording(tmp_path)
    new = np.ones(4, np.complex64)
    sigmf_io.write_sigmf(tmp_path / "x", new, 2e6, description="new")
    x, meta = sigmf_io.read_sigmf(tmp_path / "x")
    assert np.array_equal(x, new)
    assert meta["global"]["core:description"] == "new"
    assert sorted(p.name for p in tmp_path.iterdir()) == names


def test_failed_rename_keeps_old_recording(tmp_path, monkeypatch):
    import numpy as np
    import pytest

    from snappnt.io import sigmf_io

    # Calls: 1-2 move the old files to backups, 3 places the data, 4 places the metadata.
    for n in (1, 2, 3, 4):
        monkeypatch.undo()
        old, names = _old_recording(tmp_path)
        old_meta = sigmf_io.read_sigmf(tmp_path / "x")[1]
        _fail_nth_replace(monkeypatch, n)
        with pytest.raises(OSError, match="rename failed"):
            sigmf_io.write_sigmf(tmp_path / "x", np.ones(4, np.complex64), 2e6)
        monkeypatch.undo()
        x, meta = sigmf_io.read_sigmf(tmp_path / "x")
        assert np.array_equal(x, old)
        assert meta == old_meta
        assert sorted(p.name for p in tmp_path.iterdir()) == names


def test_failed_rename_without_old_recording_leaves_nothing(tmp_path, monkeypatch):
    import numpy as np
    import pytest

    from snappnt.io import sigmf_io

    _fail_nth_replace(monkeypatch, 2)
    with pytest.raises(OSError, match="rename failed"):
        sigmf_io.write_sigmf(tmp_path / "x", np.ones(4, np.complex64), 2e6)
    assert list(tmp_path.iterdir()) == []


def test_failed_restore_keeps_backups_and_names_them(tmp_path, monkeypatch):
    import numpy as np
    import pytest

    from snappnt.io import sigmf_io

    _old_recording(tmp_path)
    # Moves to backups succeed; placing the metadata fails, and so does every restore.
    _fail_nth_replace(monkeypatch, 3, from_n_on=True)
    with pytest.raises(OSError, match=r"kept as .*x\.sigmf-data\.bak.*x\.sigmf-meta\.bak"):
        sigmf_io.write_sigmf(tmp_path / "x", np.ones(4, np.complex64), 2e6)
    monkeypatch.undo()
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["x.sigmf-data.bak", "x.sigmf-meta.bak"]


def test_partial_restore_never_leaves_mismatched_pair(tmp_path, monkeypatch):
    import numpy as np
    import pytest

    from snappnt.io import sigmf_io

    old, _ = _old_recording(tmp_path)
    real = sigmf_io.Path.replace

    def replace(self, target):
        # Placing the metadata fails; restoring the data backup fails, the metadata one works.
        if self.name == "x.sigmf-meta.tmp" or self.name == "x.sigmf-data.bak":
            raise OSError("rename failed")
        return real(self, target)

    monkeypatch.setattr(sigmf_io.Path, "replace", replace)
    with pytest.raises(OSError, match=r"kept as .*x\.sigmf-data\.bak"):
        sigmf_io.write_sigmf(tmp_path / "x", np.ones(4, np.complex64), 2e6)
    monkeypatch.undo()
    assert not (tmp_path / "x.sigmf-data").exists()
    assert (tmp_path / "x.sigmf-data.bak").exists()
    assert np.array_equal(np.fromfile(tmp_path / "x.sigmf-data.bak", dtype="<c8"), old)


def test_unremovable_placed_file_keeps_all_backups(tmp_path, monkeypatch):
    import numpy as np
    import pytest

    from snappnt.io import sigmf_io

    _old_recording(tmp_path)
    _fail_nth_replace(monkeypatch, 4)

    real = sigmf_io.Path.unlink

    def unlink(self, missing_ok=False):
        if self.name.endswith(".tmp"):
            return real(self, missing_ok=missing_ok)
        raise OSError("cannot remove")

    monkeypatch.setattr(sigmf_io.Path, "unlink", unlink)
    with pytest.raises(OSError, match=r"kept as .*x\.sigmf-data\.bak.*x\.sigmf-meta\.bak"):
        sigmf_io.write_sigmf(tmp_path / "x", np.ones(4, np.complex64), 2e6)
    monkeypatch.undo()
    assert not (tmp_path / "x.sigmf-meta").exists()
    assert (tmp_path / "x.sigmf-meta.bak").exists()
    assert (tmp_path / "x.sigmf-data.bak").exists()


def test_existing_backup_is_never_overwritten(tmp_path):
    import numpy as np
    import pytest

    from snappnt.io import sigmf_io

    _old_recording(tmp_path)
    (tmp_path / "x.sigmf-meta.bak").write_text("saved", encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(FileExistsError, match=r"x\.sigmf-meta\.bak"):
        sigmf_io.write_sigmf(tmp_path / "x", np.ones(4, np.complex64), 2e6)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert (tmp_path / "x.sigmf-meta.bak").read_text(encoding="utf-8") == "saved"


def test_failed_backup_delete_logs_but_write_succeeds(tmp_path, monkeypatch, caplog):
    import re
    import warnings

    import numpy as np

    from snappnt.io import sigmf_io

    _old_recording(tmp_path)
    real = sigmf_io.Path.unlink

    def unlink(self, missing_ok=False):
        if self.name.endswith(".bak"):
            raise OSError("cannot delete")
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(sigmf_io.Path, "unlink", unlink)
    new = np.ones(4, np.complex64)
    with warnings.catch_warnings(), caplog.at_level("WARNING", logger=sigmf_io.__name__):
        warnings.simplefilter("error")  # warnings as errors must not fail a finished write
        sigmf_io.write_sigmf(tmp_path / "x", new, 2e6)
    monkeypatch.undo()
    assert np.array_equal(sigmf_io.read_sigmf(tmp_path / "x")[0], new)
    # Both backups are tried, and each failure is reported.
    assert len(re.findall(r"could not delete .*\.bak", caplog.text)) == 2


def test_unremovable_file_after_first_write_failure_is_named(tmp_path, monkeypatch):
    import numpy as np
    import pytest

    from snappnt.io import sigmf_io

    _fail_nth_replace(monkeypatch, 2)
    real = sigmf_io.Path.unlink

    def unlink(self, missing_ok=False):
        if self.name.endswith(".tmp"):
            return real(self, missing_ok=missing_ok)
        raise OSError("cannot remove")

    monkeypatch.setattr(sigmf_io.Path, "unlink", unlink)
    with pytest.raises(OSError, match=r"could not be removed: .*x\.sigmf-data"):
        sigmf_io.write_sigmf(tmp_path / "x", np.ones(4, np.complex64), 2e6)


def test_dangling_backup_link_is_not_overwritten(tmp_path):
    import numpy as np
    import pytest

    from snappnt.io import sigmf_io

    _old_recording(tmp_path)
    link = tmp_path / "x.sigmf-meta.bak"
    link.symlink_to(tmp_path / "missing")
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(FileExistsError, match=r"x\.sigmf-meta\.bak"):
        sigmf_io.write_sigmf(tmp_path / "x", np.ones(4, np.complex64), 2e6)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert link.is_symlink()
