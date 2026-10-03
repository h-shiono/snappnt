# Sky test plan (milestone M5)

This page prepares the first reception of a real NavIC satellite from the sky: the NavIC
S-band Standard Positioning Service (SPS) signal at 2492.028 MHz, mainly from NVS-01 in
geostationary orbit. It covers which satellites can be seen and where, how strong the signal
is expected to be at the receiver input, which parts the receive chain needs, how captures
can be time-stamped, and an outline of the test. Nothing has been received from the sky yet;
every C/N0 on this page is an estimate. Parts are listed as candidates only; choosing and
buying them is the maintainer's decision (GitHub issue #14).

Symbols used on this page:

- C/N0: carrier-to-noise density ratio at the receiver input, in dB-Hz.
- P_rx: received signal power at the output of an ideally matched right-hand circularly
  polarised (RHCP) antenna with 0 dBi gain, in dBW.
- G_ant: gain of the actual antenna towards the satellite, in dBic (dB relative to an
  isotropic circularly polarised antenna).
- NF: noise figure in dB; T_ant: antenna noise temperature in K; T_sys: system noise
  temperature referred to the antenna output, in K.

## The signal

From the IRNSS Signal-in-Space ICD for SPS, version 1.1 (ISRO, 2017):

| Item | Value | ICD reference |
|---|---|---|
| Carrier frequency | 2492.028 MHz | Table 1 |
| Band | 16.5 MHz, 2483.50 to 2500.00 MHz | Table 1 |
| Modulation | BPSK(1), 1.023 Mchip/s, 1023-chip code | Section 3.3; Table 6 |
| Polarisation | RHCP, transmit antenna axial ratio not above 2.0 dB | Section 3.9 |
| Minimum received power | −162.3 dBW | Section 3.8.1, Table 4 |
| Maximum received power | −157.3 dBW | Section 3.8.2, Table 5 |

The ICD defines both power levels "at the output of an ideally matched RHCP 0 dBi user
receiving antenna when the spacecraft elevation angle is higher than 5°" (sections 3.8.1 and
3.8.2). The ICD does not name a geographic region for these levels. ISRO describes the NavIC
coverage area as "India and a region up to 1500 km beyond Indian boundary"
([ISRO, Satellite Navigation Services](https://www.isro.gov.in/SatelliteNavigationServices.html)).
TODO: whether the S-band power stays at or above the ICD minimum outside that coverage area
is not stated by ISRO; it can be settled only by measurement or by a published antenna
pattern of the satellite.

## Which satellites are in service

Reported status, not verified by this project:

- In a reply in the Lok Sabha reported on 2026-07-30, the government stated that the
  operational constellation relies on IRNSS-1B, IRNSS-1I and NVS-01, and that at least four
  satellites are needed for basic positioning service
  ([Business Today, 2026-07-30](https://www.businesstoday.in/amp/india/story/only-three-satellites-left-active-centre-acknowledges-navic-standalone-navigation-gap-546285-2026-07-30)).
  The atomic clock of IRNSS-1F is reported to have stopped on 2026-03-13
  ([ETV Bharat, 2026-03-14](https://www.etvbharat.com/en/technology/indias-navigation-satellite-system-navic-goes-offline-amid-critical-satellite-loss-enn26031403113/));
  in August 2025 IRNSS-1F was still listed as one of four operational satellites
  ([GPS World, 2025-08-01](https://www.gpsworld.com/indias-navic-constellation-in-jeopardy-as-majority-of-satellites-become-defunct/)).
- NVS-02 did not reach its planned orbit after its launch in January 2025 and remains in a
  highly elliptical orbit (eccentricity 0.74 in the TLE file
  `tests/data/navic_celestrak_2026-10-03.tle`).
- NVS-01 (catalogue number 56759, international designator 2023-076A) is in geostationary
  orbit at 129.5° E ([ISRO, Satellite Navigation Services](https://www.isro.gov.in/SatelliteNavigationServices.html)).

With three satellites in service, NavIC alone cannot give a position fix (four unknowns:
three position coordinates and the receiver clock). Milestone M5 is about acquisition:
finding the signal, its code phase and its carrier frequency offset in a snapshot.

TODO: whether satellites with failed clocks still transmit an S-band signal, and with which
codes, is not known to this project. A capture would show it, but a detection of their PRN
does not by itself mean that their navigation data is usable.

## Visibility

`tools/visibility.py` computes the elevation and azimuth of each satellite in a TLE file
(two-line element set) over time for one receiver position. The position is given on the
command line and is not written to the output; do not commit a command line or output that
contains a real receiver position ([Public-safety rules](../development/public-safety.md)).

```bash
uv sync --extra sky
uv run python tools/visibility.py --tle tests/data/navic_celestrak_2026-10-03.tle \
    --lat-deg 13.0 --lon-deg 77.6 --start 2026-10-03T00:00:00Z --hours 24 --step-min 10 \
    --name NVS-01 --name 1B --name 1I -o out/visibility.csv
```

The CSV has the columns `time_utc`, `name`, `norad_id`, `elevation_deg`, `azimuth_deg`
(clockwise from north) and `range_m`. A summary per satellite (lowest and highest elevation,
share of samples above `--min-elevation-deg`, default 5° as in the ICD) goes to standard
error, with the epoch of each TLE. The tool warns when the computed times are more than
7 days from a TLE's epoch (a threshold chosen for this tool, not taken from a source: SGP4 does
not model station keeping, so an old TLE of a geostationary satellite drifts away from the real
position). For a real test, download a current TLE file first:

```bash
curl -o out/navic.tle "https://celestrak.org/NORAD/elements/gp.php?NAME=IRNSS&FORMAT=TLE"
```

The tool uses the SGP4 model (`sgp4` package, optional extra `sky`; decision D-021 in the
[decision log](../project/decisions.md)).

### Examples

Computed from the TLE file in the repository (CelesTrak, downloaded 2026-10-03) for
2026-10-03 00:00 to 24:00 UTC in 10-minute steps, at well-known places and round-number
positions:

| Position | NVS-01 elevation | NVS-01 azimuth | IRNSS-1B elevation | IRNSS-1I elevation |
|---|---|---|---|---|
| Bengaluru (13.0° N, 77.6° E) | 28.9° to 29.9° | 98° to 102° | 35.8° to 68.0° | 35.5° to 68.0° |
| New Delhi (28.6° N, 77.2° E) | 23.5° to 25.7° | 108° to 112° | 20.7° to 69.7° | 20.5° to 69.7° |
| 0°, 100° E | 55.5° to 55.7° | 86° to 94° | 29.4° to 40.1° | 29.2° to 40.0° |
| 35° N, 135° E | 46.8° to 51.1° | 189° to 190° | −17.6° to 16.3° | −17.7° to 16.4° |
| 30° S, 120° E | 51.4° to 55.7° | 18° to 19° | −4.8° to 28.4° | −5.1° to 28.5° |
| London (51.5° N, 0°) | below the horizon | — | −12.5° to 37.2° | −12.7° to 37.5° |

- NVS-01 moves little: its inclination in this TLE is 1.9°, so its elevation changes by a
  few degrees over a day and its sub-satellite longitude stays between 129.38° and 129.55° E.
- IRNSS-1B and IRNSS-1I are in inclined geosynchronous orbits (inclination about 29°) and
  move over a large part of the sky each day.

### Doppler

Computed with the same tool from the change of `range_m` over one-minute steps (2026-10-03):

| Position | NVS-01, largest Doppler | IRNSS-1B, largest Doppler |
|---|---|---|
| Bengaluru | 36 Hz | 944 Hz |
| 0°, 100° E | 19 Hz | 576 Hz |
| 35° N, 135° E | 89 Hz | 1448 Hz |

These are far smaller than the carrier offset caused by the receiver's crystal: about
30 kHz at 2492 MHz for a 12 ppm error. The frequency search range in acquisition is
therefore set by the receiver clock, as in the conducted test, not by satellite motion.

## Link budget

`tools/sky_link_budget.py` computes the C/N0 at the receiver input:

$$
C/N_0 = P_\mathrm{rx} + G_\mathrm{ant} - 10 \log_{10}(k\,T_\mathrm{sys})
$$

with Boltzmann's constant k = 1.380649 × 10⁻²³ J/K and T_sys = T_ant + T_e, where T_e is the
noise temperature of the receive chain referred to the antenna output (Friis formula; each
stage i has T_i = 290 K × (10^(NF_i/10) − 1), divided by the gain of all stages before it).
A cable or filter with loss L dB at room temperature is a stage with gain −L dB and noise
figure L dB. The tool's docstring gives the details.

```bash
uv run python tools/sky_link_budget.py --antenna-gain-dbic 3 --antenna-temp-k 100 \
    --stage cable:-0.5:0.5 --stage lna:20:1.0 --stage bpf:-2:2 --stage cable:-1:1 \
    --receiver-nf-db 5 10 15
```

### Assumptions

- **P_rx.** The ICD minimum, −162.3 dBW, unless stated otherwise. The actual power may be
  higher, up to the ICD maximum of −157.3 dBW, inside the coverage area; outside it, see the
  TODO under "The signal".
- **G_ant = 0 or 3 dBic.** Assumed values. A patch antenna typically has its highest gain
  towards the zenith and less towards low elevations; NVS-01 is at 25° to 56° elevation in
  the examples above. The real value comes from the chosen antenna's datasheet at the
  satellite's elevation. A linearly polarised antenna loses about 3 dB more on a circularly
  polarised signal.
- **T_ant = 100 K.** An assumed round value for an antenna that sees mostly sky and some
  ground. With the chain B below and a receiver NF of 10 dB, T_ant = 50 K gives 45.7 dB-Hz
  and T_ant = 200 K gives 43.5 dB-Hz, against 44.8 dB-Hz at 100 K (G_ant = 3 dBic, ICD
  minimum).
- **Receiver NF.** TODO: the noise figure of the ESP32 radio at its antenna pin is not given
  in any document this project has found. It is shown as 5, 10 and 15 dB. The conducted test
  (issue #11) can measure it: a known input level and the measured C/N0 give the noise figure
  through the conducted-test calculator (`snappnt link-budget`).
- **Implementation losses** after the receiver input (quantisation, filtering, short
  snapshots) are not part of this calculation; they are included in the simulated detection
  curves that the result is compared with.

### Chains compared

- **A:** antenna, 1 dB of cable, receiver (no external LNA).
- **B:** antenna, 0.5 dB cable, LNA with 20 dB gain and 1.0 dB NF, band-pass filter with
  2 dB loss, 1 dB cable, receiver.
- **C:** as B with 30 dB LNA gain.

C/N0 in dB-Hz, T_ant = 100 K:

| P_rx | G_ant | Chain | Receiver NF 5 dB | 10 dB | 15 dB |
|---|---|---|---|---|---|
| −162.3 dBW (ICD minimum) | 0 dBic | A | 36.5 | 30.9 | 25.7 |
| | | B | 42.6 | 41.8 | 40.0 |
| | | C | 42.8 | 42.8 | 42.5 |
| | 3 dBic | A | 39.5 | 33.9 | 28.7 |
| | | B | 45.6 | 44.8 | 43.0 |
| | | C | 45.8 | 45.8 | 45.5 |
| −157.3 dBW (ICD maximum) | 0 dBic | B | 47.6 | 46.8 | 45.0 |
| | 3 dBic | B | 50.6 | 49.8 | 48.0 |
| | | C | 50.8 | 50.8 | 50.5 |

With an LNA of low noise figure at the front, the receiver's own noise figure matters little;
without one (chain A), every dB of receiver NF costs almost a dB of C/N0. More LNA gain also
raises the level of every other signal in the band; see "Receive chain".

### Comparison with the simulated detection curves

The C/N0 needed for 50 % and 90 % detection probability, from
[Detection probability versus C/N0](../results/pd-curves.md) (false-alarm probability 1e-3):

| Condition | 50 % | 90 % | Margin to the 90 % point |
|---|---|---|---|
| ESP32-C3, 80 MSa/s, 0.2 ms snapshot | 50.2 dB-Hz | 52.0 dB-Hz | −12.0 to −6.2 dB: not expected to work |
| ESP32-C61, 4 MSa/s, 4 ms, 1 block | 37.8 dB-Hz | 40.4 dB-Hz | −0.4 to +5.4 dB |
| ESP32-C61, 4 MSa/s, 4 ms, 4 blocks | 38.7 dB-Hz | 40.6 dB-Hz | −0.6 to +5.2 dB |
| Ideal, 8.184 MSa/s, 4 ms (reference receiver) | 36.8 dB-Hz | 38.8 dB-Hz | +1.2 to +7.0 dB |

The margin is the C/N0 of chains B and C at the ICD minimum power, 40.0 to 45.8 dB-Hz over
G_ant = 0 to 3 dBic and a receiver NF of 5 to 15 dB, minus the 90 % point. The low end is
chain B with G_ant = 0 dBic and a receiver NF of 15 dB.

What this says, under the assumptions above:

- **ESP32-C3 with one 16 380-sample capture (about 0.2 ms) is not expected to detect the
  signal at the ICD minimum power**, even with an LNA. Only near the ICD maximum power with a
  good antenna (about 50.5 dB-Hz) does it reach its 50 % point. A longer coherent snapshot is
  what the ESP32-C3 lacks; its capture length is limited by the firmware
  (`max_capture_samples` in `src/snappnt/frontend/devices/esp32c3.yaml`).
- **ESP32-C61 with a 4 ms snapshot at 4 MSa/s has a few dB of margin** with an LNA. Caveat:
  those curves assume an ideal decimating filter before 4 MSa/s sampling. Whether the
  ESP32-C61 band-limits at low sample rates is open (issue #3); without band limiting, noise
  folds into the band and the margin shrinks or disappears
  ([Noise-folding loss](../results/aliasing-loss.md)).
- **A HackRF or USRP with the same antenna and LNA** can record many milliseconds without
  gaps and is the most likely receiver for a first detection. Its result gives the actual
  C/N0 at the test site, which then tells whether the ESP32 receivers can work there.
- Chain A (no LNA) does not reach the 90 % point of any ESP32 condition at the ICD minimum
  power: even with a receiver NF of 5 dB and G_ant = 3 dBic it gives 39.5 dB-Hz, enough only
  for the 50 % point of the ESP32-C61 4 ms condition.

## Receive chain

```text
antenna (RHCP, 2492 MHz) → LNA → band-pass filter 2483.5–2500 MHz → cable → receiver
          (bias supply for an active antenna or LNA, if needed)
```

- **Why a band-pass filter.** The signal sits just above the upper edge of the 2.4 GHz ISM
  band (2400 to 2483.5 MHz), which carries Wi-Fi, Bluetooth and microwave ovens; its first
  null at 2492.028 − 1.023 = 2491.005 MHz is only 7.5 MHz above that edge. The XIAO ESP32C3
  has its u.FL connector wired straight to the radio's LNA input with no RF switch or filter
  (`src/snappnt/frontend/devices/esp32c3.yaml`), and the ESP32 analog bandwidth is at least
  14 MHz (`analog_bandwidth_hz` in the same file). Strong signals in the ISM band can therefore
  reach the receiver and raise its noise floor or drive its automatic gain control down. A
  filter placed after the LNA protects the receiver; a filter before the LNA also protects the
  LNA but adds its loss directly to the noise figure.
- **LNA first.** The first active stage sets the noise figure of the chain. Keep the cable
  between antenna and LNA short, or use an antenna with a built-in LNA.
- **Gain.** Enough to make the receiver's own noise negligible (chain B already does this for
  a receiver NF up to about 10 dB), not so much that ISM-band signals overload the receiver.
  Too much gain can be reduced with a fixed attenuator in front of the receiver.
- **Bias supply.** An active antenna or an LNA powered through the coaxial cable needs a bias
  tee or a receiver that supplies DC on its antenna port. The ESP32 boards do not supply DC
  on the u.FL connector. A DC block protects a receiver input that must not see DC.
- **Never transmit.** This chain only receives. HackRF and USRP are used as receivers here;
  the rules of [Conducted test](conducted-test.md) about transmitting still apply to any
  transmission.

## Candidate parts

Candidates found by a web search on 2026-10-03. Specifications are from the linked datasheet
or the maker's or seller's page unless marked *inference*. The values for the TA1442A,
ZX60-P103LN+ and ZX60-P33ULN+ were checked a second time against their datasheets; the others
were read once and should be checked again before ordering. Prices are rough, in US dollars,
for one piece, as seen on the linked page on 2026-10-03; they change. Nothing here has been
bought or tested, and no part is chosen.

### Antennas

No antenna for NavIC S-band with a public datasheet was found. Several antennas marketed for
"NavIC" or "IRNSS" cover only the L5 band (for example HoneyComm HGA3525, Taoglas
GPVSF.25.8.A.08, u-blox ANN-MB5); check that a datasheet gives a gain at 2492 MHz before
buying.

| Part | Band and polarisation | Gain | LNA inside | Connector | Price | Source |
|---|---|---|---|---|---|---|
| L-com LCANFP1035 (flat panel) | 2400–2500 MHz, RHCP | 12 dBi nominal; axial ratio not stated | No | N female | about 118 | [l-com.com](https://www.l-com.com/2400-2500-mhz-rfid-flat-panel-antenna-rhcp-12-dbi-white-abs-n-female-ip67-lcanfp1035) |
| Video Aerial Systems SkyHammer V2, RHCP version (helical-type FPV antenna) | 2200–2550 MHz; the page title says RHCP but its specification table says linear | 5.25 dBic | No | SMA | about 50 | [team-blacksheep.com](https://www.team-blacksheep.com/products/prod:skyham_58_r_2) |
| Linear 2.4 GHz dipole or whip (for example the one supplied with an ESP32 board) | Linear | about 2 dBi, typical | No | u.FL or SMA | a few | — |

- A 12 dBi panel has a narrow beam (*inference*: some tens of degrees) and must be pointed at
  the satellite. For a geostationary satellite this is done once.
- A linear antenna loses about 3 dB against the circularly polarised signal. A left-hand
  circularly polarised antenna loses far more; check the polarisation of any antenna reused
  from another 2.4 GHz application.
- Makers of NavIC receivers that support S-band may supply an antenna with their kits; no
  datasheet was found.

### LNAs

| Part | Band | NF | Gain | Output P1dB / OIP3 | Supply | Price | Source |
|---|---|---|---|---|---|---|---|
| Mini-Circuits ZX60-P103LN+ | 50–3000 MHz | 0.6 dB at 2 GHz, 1.0 dB at 3 GHz | 10.0 dB at 2 GHz, 6.9 dB at 3 GHz | +23.2 / +42.6 dBm at 2 GHz | +5 V, 95 mA | about 119 | [datasheet](https://www.minicircuits.com/pdfs/ZX60-P103LN+.pdf) |
| Mini-Circuits ZX60-P33ULN+ | 0.4–3.0 GHz | 0.49 dB at 2 GHz, 0.90 dB at 3 GHz | 12.1 dB at 2 GHz, 8.5 dB at 3 GHz | +17.6 / +36.2 dBm at 2 GHz | +3.0 V, 56 mA | about 153 | [datasheet](https://www.minicircuits.com/pdfs/ZX60-P33ULN+.pdf) |
| Mini-Circuits ZKL-33ULN-S+ | 0.4–3.0 GHz | 0.9 dB at 2.5 GHz | 18.3 dB at 2.5 GHz | +16.2 / +38.4 dBm at 2.5 GHz | +5 V, 100 mA | about 219 | [datasheet](https://www.minicircuits.com/pdfs/ZKL-33ULN-S+.pdf) |
| Qorvo QPL9547EVB-01 (evaluation board) | 0.6–4.2 GHz | 0.48 dB at 2.5 GHz (board loss removed) | 17.6 dB | +21.9 / +38.5 dBm | +5 V, 65 mA | about 138 (long lead time seen) | [Digi-Key](https://www.digikey.com/en/products/detail/qorvo/QPL9547EVB-01/24717847) |

- All four have SMA connectors and are powered through their own supply terminal, not through
  the coaxial cable.
- The two ZX60 amplifiers have only about 7 to 12 dB of gain near 2.5 GHz. One of them alone
  does not make the receiver's noise figure negligible: with a 10 dB, 0.8 dB NF stage in
  place of the LNA in chain B, the C/N0 at the ICD minimum and G_ant = 3 dBic is 43.6, 40.2
  and 35.8 dB-Hz for a receiver NF of 5, 10 and 15 dB; with two such stages, one before and one
  after the filter, it is 45.4, 44.7 and 43.0 dB-Hz (`tools/sky_link_budget.py`).
- The values for the QPL9547 come from the maker's document as summarised by a search; the
  page itself could not be read. TODO: check against the Qorvo datasheet before ordering.
- *Inference:* a high OIP3 matters because strong ISM-band signals reach the LNA before the
  filter; the ZX60-P103LN+ has the highest OIP3 of these.

### Band-pass filters

| Part | Passband | Insertion loss | Stated rejection | Package | Price | Source |
|---|---|---|---|---|---|---|
| Tai-Saw TA1442A (SAW) | 2489.5–2494.5 MHz | 1.55 dB typical, 2.0 dB max | 33 dB min (40 typical) from DC to 2390 MHz; 43 dB min (50 typical) from 2575 to 3000 MHz | 3.0 × 3.0 mm, surface mount; +10 dBm max input | about 28 | [datasheet](https://static.chipdip.ru/lib/274/DOC042274758.pdf), [Digi-Key](https://www.digikey.com/en/products/detail/tst/TA1442A/16907283) |
| Spectron SPT2492M3030A (SAW) | 2487–2497 MHz | 2.5 dB typical, 3.0 dB max | 32 dB min (37 typical) from 1616 to 2400 MHz; 45 dB min from 2600 to 3000 MHz | 3.0 × 3.0 mm, surface mount | not found | [datasheet](https://static.chipdip.ru/lib/451/DOC036451464.pdf) |
| Anatech AE2492CB1845 (ceramic) | 2483.5–2500 MHz | below 0.6 dB | above 45 dB at 1610–1626.5 MHz | 7.7 × 6.1 mm, surface mount | not listed | [anatechelectronics.com](https://anatechelectronics.com/2491-75-mhz-ceramic-band-pass-filter-1.html) |

- **No datasheet found states the rejection between 2400 and 2483.5 MHz**, the band that
  matters here. The two SAW datasheets stop at 2390 and 2400 MHz. The ceramic filter is
  specified against 1610–1626.5 MHz (the band of satellite-phone uplinks), not against Wi-Fi.
- *Inference:* a 5 MHz wide SAW filter centred at 2492 MHz probably rejects 2450 MHz well but
  2483.5 MHz, 6 MHz below its passband, only modestly. A 16.5 MHz wide ceramic filter
  probably rejects little at 2450 MHz.
- No connectorised filter that passes 2492 MHz and rejects the ISM band was found. Common
  connectorised 2.4 GHz filters pass the whole 2400–2500 MHz band and do not help.
- *Inference:* the practical routes are a SAW filter such as the TA1442A on a small board with
  SMA connectors (possibly two in cascade, with an LNA between them), or a custom cavity
  filter. Either should be measured with a vector network analyser before use; TODO: settle
  the rejection at 2483.5 and 2450 MHz that way.

### Bias supply

- HackRF One: software-controlled antenna-port power, at most 50 mA at 3.0 to 3.3 V
  ([HackRF documentation](https://hackrf.readthedocs.io/en/latest/hackrf_one.html)).
- USRP B210 class: no bias supply on the RF ports (reported on the Ettus mailing list, not in a
  specification sheet).
- ESP32 boards: none on the u.FL connector.
- An active antenna therefore needs an external bias tee and supply. The connectorised LNAs
  above have their own supply terminal.

### GNSS receivers with a PPS output (for time-stamping options 2 and 3)

| Part | PPS accuracy stated | Connector, supply | Price | Source |
|---|---|---|---|---|
| SparkFun GPS Breakout NEO-M9N, SMA (u-blox NEO-M9N) | time pulse 30 ns | SMA, 3.3 V | about 77 | [sparkfun.com](https://www.sparkfun.com/sparkfun-gps-breakout-neo-m9n-sma-qwiic.html) |
| Adafruit Ultimate GPS Breakout v3 (PA1616S) | 10 ns jitter; absolute accuracy not stated | u.FL and internal patch, 3.0–5.5 V | about 30 | [adafruit.com](https://www.adafruit.com/product/746) |
| SparkFun GNSS Timing Breakout ZED-F9T | 5 ns absolute | SMA, USB-C | about 310 | [sparkfun.com](https://www.sparkfun.com/sparkfun-gnss-timing-breakout-zed-f9t-qwiic.html) |

*Inference:* any of these is far more precise than snapshot time-stamping needs; the limit is
the delay between the host and the start of the capture.

## Time-stamping captures

### What is recorded now

`snappnt capture` reads the host clock immediately before sending each capture command and
writes it into that recording as `snappnt:host_time_utc` and `core:datetime`
(`src/snappnt/io/espsdr_capture.py`, `src/snappnt/cli.py`). The error of this time stamp is
the error of the host clock plus the delay from the command to the first sample (serial
transfer, command parsing and capture set-up in the firmware). TODO: the delay has not been
measured. The firmware reports a `<capture-microseconds>` value with each capture; it is the
time measured around the capture including set-up, not a time stamp
([ESP-SDR serial protocol](../design/espsdr-protocol.md)). A host clock kept by NTP is
usually within some milliseconds of UTC; this is a typical value, not measured here.

### What accuracy is needed

- **Visibility and Doppler prediction:** seconds to minutes are enough. NVS-01's Doppler
  changes by less than 100 Hz over a day in the examples above.
- **Acquisition:** none. Acquisition searches code phase and frequency without using time.
- **A position from snapshots** (later, when enough satellites are in service): snapshot
  positioning methods solve for a coarse time error together with the position, but need a
  time within some seconds to start with; the satellite positions are computed for that time,
  and a time error multiplies the range rates (up to about 170 m/s for IRNSS-1B in the
  examples above). Millisecond-level time stamps would remove the need to solve for time.

### Options

1. **Host clock, as now.** No change. Accuracy depends on the host clock and the unmeasured
   command delay. Enough for M5 (acquisition only).
2. **Host clock checked against a GNSS receiver on the host.** A GNSS receiver with a pulse
   per second (PPS) output connected to the host (for example through a serial port's control
   line) keeps the host clock close to UTC. No firmware change; the command delay remains.
3. **GNSS PPS into a GPIO of the ESP32, latched by the firmware.** The firmware would record
   the time of the capture start relative to the last PPS edge and report it. This gives the
   best accuracy but needs a firmware change. Under decision D-015
   ([decision log](../project/decisions.md)) the ESP-SDR firmware is used unmodified, and a
   change is first proposed upstream. Not decided here; this is the maintainer's decision.
4. **Recording the PPS in the samples.** Coupling a PPS-derived marker into the RF input
   would put the time in the samples themselves, but would disturb the snapshot and is not
   recommended.

## Test procedure outline

1. Download a current TLE file and run `tools/visibility.py` for the test site (position on
   the command line only). Note NVS-01's azimuth and elevation, and the times when IRNSS-1B
   and IRNSS-1I are high.
2. Place the antenna with a clear view in the direction of NVS-01, away from Wi-Fi access
   points and microwave ovens.
3. **Reference receiver first.** Record with a HackRF or USRP through the same antenna, LNA
   and filter: a few seconds at 4 to 8 MSa/s centred near 2492 MHz. Acquire with a long
   snapshot and a frequency search covering the receiver's crystal error. Record the
   detected PRNs and the estimated C/N0.
4. **ESP32 receivers.** With the same chain, capture with `snappnt capture` and acquire. On
   the ESP32-C3 expect no detection at the ICD minimum power (see the link budget); on the
   ESP32-C61, capture 4 ms at 4 MSa/s when long captures are available (milestone M4).
5. Write the result as a page under [Results](../results/index.md): C/N0 found by each
   receiver, detection or not, and the comparison with this page's estimates. No receiver
   position is written.

## Open decisions (maintainer)

- **Parts of the receive chain:** antenna, LNA, band-pass filter, cables and bias supply,
  from the candidates above.
- **Time-stamping:** whether to propose a PPS input to the ESP-SDR firmware upstream (option
  3), or stay with the host clock (options 1 and 2).
- **Order of the tests:** whether the first sky test uses the reference receiver alone, as
  proposed above, before any ESP32 capture.
