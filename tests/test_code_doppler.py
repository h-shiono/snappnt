"""Code Doppler compensation in acquisition (issue #72)."""

from dataclasses import replace
from pathlib import Path

import pytest

from snappnt.cli import main
from snappnt.eval import sweep
from snappnt.rx import acquire
from snappnt.signals import load_signal
from snappnt.sim import generate, load_scenario

from .acquire_reference import acquire_reference

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"


@pytest.mark.parametrize("scenario", ["navic_s_esp32c3.yaml", "navic_s_esp32c61_4msps.yaml"])
def test_off_matches_reference(scenario):
    # code_doppler=False gives the result of the frozen pre-change implementation.
    scn = load_scenario(SCENARIOS / scenario)
    spec = load_signal(scn.signal)
    x, _ = generate(scn)
    fs = scn.receiver.sample_rate_hz
    kw = dict(freq_range_hz=(-40e3, 40e3), n_blocks=4)
    new = acquire(x, fs, spec, 10, code_doppler=False, **kw)
    ref = acquire_reference(x, fs, spec, 10, **kw)
    assert new.code_phase_chips == ref.code_phase_chips
    assert new.freq_offset_hz == ref.freq_offset_hz
    assert new.n_cells == ref.n_cells
    assert new.metric == pytest.approx(ref.metric, rel=1e-4)


def _long_snapshot(cn0_dbhz=36.0, doppler_rate_hzps=0.0):
    # -10 ppm crystal error, direct reception: carrier about +24.9 kHz at 2492 MHz, and the code
    # drifts about 2 chips over 0.2 s relative to the nominal chip rate.
    scn = load_scenario(SCENARIOS / "navic_s_esp32c61_4msps.yaml")
    rx = replace(scn.receiver, n_samples=800_000, clock_offset_ppm=-10.0)
    sat = replace(
        scn.satellites[0],
        cn0_dbhz=cn0_dbhz,
        code_phase_chips=300.4,
        doppler_rate_hzps=doppler_rate_hzps,
    )
    scn = replace(scn, receiver=rx, satellites=(sat,), seed=1)
    x, truth = generate(scn)
    return x, rx, sat, load_signal(scn.signal), truth["satellites"][0]


def test_long_snapshot_with_clock_error():
    x, rx, sat, spec, t = _long_snapshot()
    assert t["expected_freq_offset_hz"] == pytest.approx(24_920.28, abs=0.01)

    kw = dict(freq_range_hz=(20e3, 30e3), n_blocks=50)
    fs = rx.sample_rate_hz
    plain = acquire(x, fs, spec, sat.prn, **kw)
    comp = acquire(x, fs, spec, sat.prn, code_doppler=True, **kw)

    assert comp.detected
    assert abs(comp.code_phase_chips - t["code_phase_chips"]) < 0.25
    assert abs(comp.freq_offset_hz - t["expected_freq_offset_hz"]) <= comp.freq_step_hz
    assert comp.metric > plain.metric
    assert comp.n_cells == plain.n_cells


def test_long_snapshot_with_rate_search():
    # Several groups of frequency bins together with three Doppler-rate hypotheses, 0, 1250 and
    # 2500 Hz/s. The simulated rate is 1250 Hz/s, which moves the carrier by 250 Hz (two bins)
    # over 0.2 s, so the middle hypothesis wins and gives the result of a search at that rate.
    x, rx, sat, spec, t = _long_snapshot(cn0_dbhz=40.0, doppler_rate_hzps=1250.0)
    kw = dict(freq_range_hz=(20e3, 30e3), n_blocks=50, code_doppler=True)
    fs = rx.sample_rate_hz
    single = acquire(x, fs, spec, sat.prn, doppler_rate_hzps=1250.0, **kw)
    searched = acquire(
        x, fs, spec, sat.prn, rate_range_hzps=(0.0, 2500.0), rate_step_hzps=1250.0, **kw
    )
    assert searched.rate_step_hzps == 1250.0
    assert searched.n_cells == 3 * single.n_cells
    assert searched.doppler_rate_hzps == 1250.0
    assert searched.code_phase_chips == single.code_phase_chips
    assert searched.freq_offset_hz == single.freq_offset_hz
    assert searched.metric == pytest.approx(single.metric, rel=1e-6)
    assert abs(searched.code_phase_chips - t["code_phase_chips"]) < 0.25


def test_sweep_rejects_external_lo():
    scn = load_scenario(SCENARIOS / "cband_bpsk_generic_lowside.yaml")
    with pytest.raises(ValueError, match="lo_hz"):
        sweep(scn, [48.0], 1, code_doppler=True)


def test_cli_sweep_rejects_external_lo(capsys):
    args = ["sweep", str(SCENARIOS / "cband_bpsk_generic_lowside.yaml"), "--cn0", "48"]
    assert main([*args, "--trials", "1", "--code-doppler"]) == 2
    assert "lo_hz" in capsys.readouterr().err


def test_cli_acquire_rejects_external_lo(tmp_path, capsys):
    out = tmp_path / "lowside"
    assert main(["sim", str(SCENARIOS / "cband_bpsk_generic_lowside.yaml"), "-o", str(out)]) == 0
    assert main(["acquire", str(out), "--prn", "5", "--code-doppler"]) == 2
    assert "lo_hz" in capsys.readouterr().err


def test_cli_acquire_with_code_doppler(tmp_path, capsys):
    out = tmp_path / "c3"
    assert main(["sim", str(SCENARIOS / "navic_s_esp32c3.yaml"), "-o", str(out)]) == 0
    capsys.readouterr()
    args = ["acquire", str(out), "--prn", "10", "--freq-span", "40000", "--code-doppler"]
    assert main(args) == 0
    assert "OK" in capsys.readouterr().out
