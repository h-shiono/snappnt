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
