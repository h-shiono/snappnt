"""tools/sky_link_budget.py. Expected values are worked by hand (see the comments)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "sky_link_budget", ROOT / "tools" / "sky_link_budget.py"
)
slb = importlib.util.module_from_spec(_spec)
sys.modules["sky_link_budget"] = slb
_spec.loader.exec_module(slb)

# 10*log10(k) with k = 1.380649e-23 J/K: -228.599 dB(W/K/Hz)
K_DB = -228.599
NF_F2_DB = 3.0103  # F = 2   -> T = 290 K
NF_F11_DB = 10.4139  # F = 11 -> T = 2900 K


def test_noise_temperature():
    assert slb.noise_temp_k(0.0) == 0.0
    assert slb.noise_temp_k(NF_F2_DB) == pytest.approx(290.0, abs=0.01)
    with pytest.raises(ValueError):
        slb.noise_temp_k(-1.0)


def test_cascade_two_stages():
    # T = 290 + 2900 / 10 = 580 K
    stages = [slb.Stage("lna", 10.0, NF_F2_DB), slb.Stage("rx", 0.0, NF_F11_DB)]
    assert slb.cascade_temp_k(stages) == pytest.approx(580.0, abs=0.05)


def test_passive_loss_before_receiver():
    # cable 3.0103 dB (G = 1/2, T = 290 K), receiver F = 2: T = 290 + 290 * 2 = 870 K
    stages = [slb.Stage("cable", -NF_F2_DB, NF_F2_DB), slb.Stage("rx", 0.0, NF_F2_DB)]
    assert slb.cascade_temp_k(stages) == pytest.approx(870.0, abs=0.05)


def test_sky_cn0_hand_case():
    # T_ant 0 K, receiver F = 2: T_sys = 290 K, N0 = -228.599 + 24.624 = -203.975 dBW/Hz,
    # C/N0 = -162.3 + 0 + 203.975 = 41.675 dB-Hz
    r = slb.sky_cn0(-162.3, 0.0, 0.0, [], NF_F2_DB)
    assert r.system_temp_k == pytest.approx(290.0, abs=0.01)
    assert r.n0_dbw_hz == pytest.approx(K_DB + 24.624, abs=0.002)
    assert r.cn0_dbhz == pytest.approx(41.675, abs=0.002)


def test_sky_cn0_with_lna_and_antenna():
    # T_ant 290 K, LNA G = 10 F = 2, receiver F = 11: T_sys = 290 + 580 = 870 K
    # N0 = -228.599 + 29.395 = -199.204; C/N0 = -162.3 + 3 + 199.204 = 39.904 dB-Hz
    r = slb.sky_cn0(-162.3, 3.0, 290.0, [slb.Stage("lna", 10.0, NF_F2_DB)], NF_F11_DB)
    assert r.chain_temp_k == pytest.approx(580.0, abs=0.05)
    assert r.cn0_dbhz == pytest.approx(39.904, abs=0.003)


def test_default_power_is_icd_minimum():
    assert slb.NAVIC_S_MIN_POWER_DBW == -162.3


def test_rejects_bad_values():
    with pytest.raises(ValueError):
        slb.sky_cn0(float("nan"), 0, 100, [], 5)
    with pytest.raises(ValueError):
        slb.sky_cn0(-162.3, 0, -1, [], 5)


def test_cli(capsys):
    args = ["--antenna-gain-dbic", "0", "--antenna-temp-k", "0", "--receiver-nf-db", "3.0103"]
    assert slb.main(args) == 0
    out = capsys.readouterr().out
    assert "41.68" in out and "-162.30 dBW" in out


def test_cli_rejects_bad_stage():
    base = ["--antenna-gain-dbic", "0", "--antenna-temp-k", "100", "--receiver-nf-db", "5"]
    for bad in ("lna:20", "lna:x:1", "lna:20:-1", "lna:20:nan"):
        with pytest.raises(SystemExit):
            slb.main([*base, "--stage", bad])
