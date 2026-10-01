"""The batched acquisition gives the same result as the per-bin loop it replaced."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from snappnt.rx import acquire
from snappnt.signals import load_signal
from snappnt.sim import generate, load_scenario

from .acquire_reference import acquire_reference

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"


def _snapshot(name, cn0_dbhz=None, seed=7):
    scn = load_scenario(SCENARIOS / name)
    sat = scn.satellites[0]
    if cn0_dbhz is not None:
        scn = replace(scn, satellites=(replace(sat, cn0_dbhz=cn0_dbhz),), seed=seed)
    spec = load_signal(scn.signal)
    x, truth = generate(scn)
    return x, scn, spec, truth["satellites"][0]["prn"]


@pytest.mark.parametrize("scenario", ["navic_s_esp32c3.yaml", "navic_s_esp32c61_4msps.yaml"])
@pytest.mark.parametrize("n_blocks", [1, 4])
@pytest.mark.parametrize("present", [True, False])
@pytest.mark.parametrize("refine", [False, True])
def test_matches_reference(scenario, n_blocks, present, refine):
    x, scn, spec, prn = _snapshot(scenario, None if present else -50.0)
    kw = dict(
        center_offset_hz=scn.receiver.baseband_offset_hz,
        freq_range_hz=(-20e3, 20e3),
        n_blocks=n_blocks,
        refine=refine,
    )
    fs = scn.receiver.sample_rate_hz
    new = acquire(x, fs, spec, prn, **kw)
    ref = acquire_reference(x, fs, spec, prn, **kw)
    assert new.detected == ref.detected
    assert new.n_cells == ref.n_cells
    assert new.freq_offset_hz == ref.freq_offset_hz or refine
    assert new.metric == pytest.approx(ref.metric, rel=1e-4)
    assert new.cn0_dbhz_est == pytest.approx(ref.cn0_dbhz_est, abs=1e-3)
    if not refine:
        assert new.code_phase_chips == ref.code_phase_chips
        assert new.freq_offset_hz == ref.freq_offset_hz
    else:
        assert np.isclose(new.code_phase_chips, ref.code_phase_chips, atol=1e-3)
        assert new.freq_offset_hz == pytest.approx(ref.freq_offset_hz, abs=1.0)


def test_doppler_rate_matches_reference():
    x, scn, spec, prn = _snapshot("navic_s_esp32c61_4msps.yaml")
    kw = dict(
        center_offset_hz=scn.receiver.baseband_offset_hz,
        freq_range_hz=(-5e3, 5e3),
        doppler_rate_hzps=2e3,
        n_blocks=2,
    )
    fs = scn.receiver.sample_rate_hz
    new = acquire(x, fs, spec, prn, **kw)
    ref = acquire_reference(x, fs, spec, prn, **kw)
    assert (new.detected, new.code_phase_chips, new.freq_offset_hz) == (
        ref.detected,
        ref.code_phase_chips,
        ref.freq_offset_hz,
    )
    assert new.metric == pytest.approx(ref.metric, rel=1e-4)


@pytest.mark.parametrize("cn0_dbhz", [42.1, 42.2, 42.3, 42.4])
def test_near_threshold_matches_reference(cn0_dbhz):
    """With the metric within 10 % of the threshold, single precision must not change the result."""
    x, scn, spec, prn = _snapshot("navic_s_esp32c61_4msps.yaml", cn0_dbhz, seed=7)
    kw = dict(
        center_offset_hz=scn.receiver.baseband_offset_hz,
        freq_range_hz=(-20e3, 20e3),
        n_blocks=4,
    )
    fs = scn.receiver.sample_rate_hz
    new = acquire(x, fs, spec, prn, **kw)
    ref = acquire_reference(x, fs, spec, prn, **kw)
    assert 0.9 < ref.metric / ref.threshold < 1.1  # the case is really near the threshold
    assert new.detected == ref.detected
    assert new.metric == pytest.approx(ref.metric, rel=1e-4)
    assert new.code_phase_chips == ref.code_phase_chips
    assert new.freq_offset_hz == ref.freq_offset_hz


def test_working_memory_independent_of_snapshot_length():
    """Peak memory of the power grid stays near the batch budget for a long recording."""
    import tracemalloc

    from snappnt.rx import acquisition

    fs = 4e6
    n_blocks, block = 2, 400_000  # 0.2 s in total, 800k samples
    n = n_blocks * block
    rng = np.random.default_rng(1)
    x = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    k = 4000
    nfft = 1 << int(np.ceil(np.log2(2 * block + k)))
    rep_f = [np.zeros(nfft, dtype=np.complex64)] * n_blocks
    carriers = np.arange(200) * 5.0
    tracemalloc.start()
    acquisition._power_grid(x, fs, carriers, 0.0, rep_f, block, n_blocks, nfft, k)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    # Before bounding, 64 bins x 800k samples x 8 bytes = 410 MB per temporary array.
    assert peak < 12 * acquisition._BATCH_BYTES
