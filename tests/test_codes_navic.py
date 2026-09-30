"""ICD check: NavIC SPS codes against IRNSS SIS ICD for SPS v1.1 (ISRO, 2017), Table 7.

The expected values below are the "first 10 chips (octal)" column of the ICD, typed in
independently of the G2 initial states used by the generator. If a value here ever needs
changing, re-check it against the printed ICD, not against the generator output.
"""

import numpy as np
import pytest

from snappnt.signals import get_code, load_signal
from snappnt.signals.codes.lfsr import first_chips_octal

ICD_FIRST_CHIPS_OCTAL = {
    "navic_l5_sps": [
        "0130", "1731", "0713", "1215", "0117", "1624", "1753",
        "1317", "1547", "0233", "1663", "0203", "0455", "1025",
    ],
    "navic_s_sps": [
        "1420", "1202", "0716", "1524", "0556", "1323", "1561",
        "1331", "0361", "0501", "0156", "0226", "1272", "1362",
    ],
}  # fmt: skip

CASES = [(sig, prn) for sig, table in ICD_FIRST_CHIPS_OCTAL.items() for prn in range(1, 15)]


@pytest.mark.icd
@pytest.mark.parametrize("signal,prn", CASES)
def test_first_chips_match_icd(signal, prn):
    spec = load_signal(signal)
    code = get_code(spec, prn)
    assert first_chips_octal(code) == ICD_FIRST_CHIPS_OCTAL[signal][prn - 1]


@pytest.mark.parametrize("signal", sorted(ICD_FIRST_CHIPS_OCTAL))
def test_code_shape(signal):
    spec = load_signal(signal)
    for prn in spec.prns():
        code = get_code(spec, prn)
        assert code.size == 1023
        assert code.dtype == np.int8
        assert set(np.unique(code)) <= {-1, 1}


@pytest.mark.parametrize("signal", sorted(ICD_FIRST_CHIPS_OCTAL))
def test_gold_code_cross_correlation(signal):
    """Periodic cross-correlation of 10-stage Gold codes takes only the values -65, -1, 63."""
    spec = load_signal(signal)
    codes = [get_code(spec, p).astype(np.int32) for p in spec.prns()]
    allowed = {-65, -1, 63}
    for i in range(len(codes)):
        for j in range(i + 1, len(codes)):
            xc = np.real(np.fft.ifft(np.fft.fft(codes[i]) * np.conj(np.fft.fft(codes[j]))))
            assert set(np.rint(xc).astype(int)) <= allowed


def test_l5_and_s_codes_differ():
    s, l5 = load_signal("navic_s_sps"), load_signal("navic_l5_sps")
    for prn in range(1, 15):
        assert not np.array_equal(get_code(s, prn), get_code(l5, prn))
