"""GPS L1 C/A against IS-GPS-200 Table 3-Ia: an independent check of the shared LFSR conventions."""

import pytest

from snappnt.signals import get_code, load_signal
from snappnt.signals.codes.lfsr import first_chips_octal, lfsr_bits

IS_GPS_200_FIRST_CHIPS_OCTAL = {
    1: "1440", 2: "1620", 3: "1710", 4: "1744", 5: "1133",
    6: "1455", 7: "1131", 8: "1454", 9: "1626", 10: "1504",
}  # fmt: skip


@pytest.mark.icd
@pytest.mark.parametrize("prn,expected", sorted(IS_GPS_200_FIRST_CHIPS_OCTAL.items()))
def test_gps_first_chips(prn, expected):
    assert first_chips_octal(get_code(load_signal("gps_l1ca"), prn)) == expected


def test_maximal_length_period():
    """G1 and G2 are maximal-length: period 1023, and 512 ones per period."""
    for taps in ((3, 10), (2, 3, 6, 8, 9, 10)):
        bits = lfsr_bits("1" * 10, taps, 2046)
        assert (bits[:1023] == bits[1023:]).all()
        assert int(bits[:1023].sum()) == 512


def test_lfsr_rejects_bad_taps():
    with pytest.raises(ValueError):
        lfsr_bits("1" * 10, (3, 9), 10)
