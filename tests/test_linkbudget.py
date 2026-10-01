"""Link budget calculator. Expected values are worked by hand (see the comments)."""

from __future__ import annotations

from pathlib import Path

import pytest

from snappnt import cli
from snappnt.eval.linkbudget import (
    check_injected_noise,
    cn0_dbhz,
    evaluate_branches,
    input_level_dbm,
    noise_density_dbm_hz,
)

ROOT = Path(__file__).resolve().parents[1]
PATH_LOSSES = [30, 3, 30, 1]  # attenuator, splitter, attenuator, DC block


def test_input_level_hand_example():
    # -10 - 30 - 3 - 30 - 1 = -74 dBm
    assert input_level_dbm(-10, PATH_LOSSES) == pytest.approx(-74.0)


def test_no_losses_and_negative_loss():
    assert input_level_dbm(-10, []) == -10
    with pytest.raises(ValueError):
        input_level_dbm(-10, [30, -1])


def test_noise_density_and_cn0():
    # kT0 = -173.98 dBm/Hz (printed as -174), NF 5 dB -> -169 dBm/Hz; -74 + 169 = 95 dB-Hz
    assert noise_density_dbm_hz(5) == pytest.approx(-169.0, abs=0.03)
    assert cn0_dbhz(-74, 5) == pytest.approx(95.0, abs=0.03)
    with pytest.raises(ValueError):
        noise_density_dbm_hz(5, 0)


def test_injected_noise_passes():
    # N0_inj = -74 - 50 = -124 dBm/Hz, 45 dB above -169; error 10*log10(1 + 10^-4.5) = 0.00014 dB
    c = check_injected_noise(50, -74, 5)
    assert c.injected_dbm_hz == pytest.approx(-124.0)
    assert c.ratio_db == pytest.approx(45.0, abs=0.03)
    assert c.ok
    assert c.effective_cn0_dbhz == pytest.approx(50.0, abs=0.001)
    assert c.error_db == pytest.approx(0.0, abs=0.001)


def test_injected_noise_fails():
    # P_in -130, C/N0 50 -> N0_inj = -180, 11 dB below -169. Total = 10*log10(1e-18 + 1e-16.9)
    # = -168.67 dBm/Hz, so C/N0 = -130 + 168.67 = 38.67 dB-Hz.
    c = check_injected_noise(50, -130, 5)
    assert c.ratio_db == pytest.approx(-11.0, abs=0.03)
    assert not c.ok
    assert c.effective_cn0_dbhz == pytest.approx(38.67, abs=0.03)
    assert c.error_db == pytest.approx(11.33, abs=0.03)


def test_margin_boundary():
    # N0_inj = -159 is exactly 10 dB above -169 (NF 5, kT0 rounded): use margin just either side
    p_in, cn0 = -109, 50  # N0_inj = -159
    ratio = check_injected_noise(cn0, p_in, 5).ratio_db
    assert check_injected_noise(cn0, p_in, 5, margin_db=ratio).ok
    assert not check_injected_noise(cn0, p_in, 5, margin_db=ratio + 0.01).ok


def test_branches():
    r = evaluate_branches(-10, [30], {"a": ([3, 30, 1], 5), "b": ([3, 30], 6)})
    assert [x.name for x in r] == ["a", "b"]
    assert r[0].p_in_dbm == pytest.approx(-74.0)
    assert r[1].p_in_dbm == pytest.approx(-73.0)
    assert r[1].cn0_dbhz == pytest.approx(-73 + 168, abs=0.03)


def test_cli(capsys):
    args = ["link-budget", "--gen-dbm", "-10", "--esp32-nf-db", "5"]
    for lab, db in (("att", 30), ("split", 3), ("att2", 30), ("dc", 1)):
        args += ["--loss", f"{lab}={db}"]
    assert cli.main([*args, "--scenario-cn0-dbhz", "50"]) == 0
    out = capsys.readouterr().out
    assert "-74.00 dBm" in out and "94.98 dB-Hz" in out and "ok" in out
    assert cli.main([*args[:5], "--loss", "130", "--scenario-cn0-dbhz", "50"]) == 1
    assert "FAILED" in capsys.readouterr().out
    assert cli.main(["link-budget", "--gen-dbm", "0", "--esp32-nf-db", "5", "--loss", "-3"]) == 2


def test_template_linked():
    assert (ROOT / "docs/guides/conducted-test-log-template.md").is_file()
    assert "conducted-test-log-template.md" in (ROOT / "docs/guides/conducted-test.md").read_text()
    assert "conducted-test-log-template.md" in (ROOT / "mkdocs.yml").read_text()
