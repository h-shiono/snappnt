# ESP32-C61 low sample rates and long captures

This page answers two questions about the ESP32-C61 running the ESP-SDR firmware: how its low
sample rates are produced, and whether continuous capture (many milliseconds without gaps) is
possible. It was written for issue #13.

**Status: read from the firmware source only. Nothing on this page has been verified on
hardware.** Hardware verification is tracked in issue #11. Estimates are labelled as
estimates; values not found in a source are marked `TODO` with what would settle them.

## Sources and how to read the citations

Citations have the form `file:line`. They refer to the firmware repository
<https://github.com/ESPARGOS/esp-sdr> at commit `4935ac29f7baabd552084534b2a346669937d981`,
the same commit as in [ESP-SDR serial protocol](espsdr-protocol.md). Short names:

| Short name | File |
|---|---|
| `receiver.c` | `main/families/c5_c6_c61/receiver.c` (shared by ESP32-C5, C6 and C61) |
| `chip.h` | `main/targets/esp32c61/chip.h` |
| `rx-controls.md` | `docs/rx-controls.md` |

Terms: a *sample* is one complex I/Q pair. A *word* is one 32-bit entry of the capture memory.
A *rate index* is the second argument of a capture command; for the C61 it is 0 to 5, and
`sample_rates_sps` in `frontend/devices/esp32c61.yaml` lists the rates it selects.

## How low sample rates are produced

Facts:

- The rate index is passed unchanged, as `divider`, to `stock_capture`
  (`receiver.c:132`, `:165`, `:313`). `stock_capture` writes it into bits 21 and up of the
  capture-mode register at `0x600a9008`, together with source selector 15 in bits 17 to 20
  (`chip.h:20-21`).
- The firmware contains no decimation, FIR filter or resampling step. Between the capture
  hardware and the host it only checks the capture, packs it (`pack_iq`, `pack_iq8`,
  `receiver.c:102-119`), computes a CRC and sends it (`receiver.c:180-185`).
- The receive filters that the firmware can set are an analog low-pass capacitance of
  13 to 54 MHz (`BANDWIDTH` and `ALPF`; `receiver.c:280-281`, `:291-296`) and a PHY digital
  filter mode with the values 0, 4, 8 or 12 (`LPF`; `receiver.c:298-304`).
- The firmware documentation says that these filters give approximate noise widths and
  "do not guarantee alias-free reception at every sample rate" (`rx-controls.md:45-47`).

What is not known:

- Whether the capture hardware band-limits the signal before the clock is divided, or only
  divides the clock, is not stated in the firmware or its documentation. The absence of a
  decimation filter in the firmware is not proof that the hardware has none.
  `low_rate_method` in `frontend/devices/esp32c61.yaml` therefore stays `unknown`.
- `TODO`: the ESP32-C61 technical reference manual was not consulted for this page. Reading
  its chapter on the capture hardware (the registers around `0x600a9000`) could settle the
  question, if the register is documented at all.
- What would settle it by measurement: the noise floor and a tone alias check at each rate
  index, as in [Aliasing loss](../results/aliasing-loss.md). If noise folds into the band at
  4 MS/s, the clock is only divided.

## How the capture memory works: there is no ring buffer

- One 64 KiB bank (bank 3, addresses `0x40830000` to `0x40840000`) holds the capture
  (`chip.h:4`, `:9`). The usable size is 16380 words (`chip.h:3`); the firmware writes four
  marker words after the capture and checks them for overruns (`receiver.c:136`, `:177-179`).
- A capture is one finite, software-triggered snapshot. The firmware writes the sample count
  `n` into the control register, pulses the trigger bits and polls the completion bit 18 for
  at most 20 ms (`chip.h:30-38`). The comment says that the continuous gate (bit 17) stays off
  (`chip.h:28-29`).
- A comment in the C5 code says that setting bit 17, as "the C61 continuous backend" does,
  "produced only a short, incomplete snapshot" on the C5 (`receiver.c:146-148`). The code of
  that C61 continuous backend is not in this repository.
- The firmware keeps no write pointer. A capture that did not fill the buffer is detected
  by a marker word left in the data (`receiver.c:135`, `:174-176`); an overrun is detected by
  the four marker words after the data (`receiver.c:136`, `:177-179`).
- The CPU, the capture hardware and a bank-ownership register (`SRAM_OWNER_REG`) are involved.
  Ownership goes to the capture hardware for the snapshot and back afterwards
  (`chip.h:25`, `:40`).
- The C61 firmware path does not use PSRAM: `receiver.c` and `chip.h` contain no PSRAM
  access or initialisation.
- Consecutive captures have gaps, because the host drains the buffer over USB between them
  (`receiver.c:254-257`; firmware `README.md:135`).

## Feasibility estimate at 4 MS/s

All numbers in this section are estimates from arithmetic on the inputs listed. Nothing was
measured.

| Quantity | Value | Input |
|---|---|---|
| Duration of one full capture at 4 MS/s | 16380 / 4 MS/s = 4.095 ms | `chip.h:3` |
| Duration of one full capture at 80 MS/s | 16380 / 80 MS/s = 204.75 µs | `chip.h:3` |
| Data rate, 2 bits per component | 4 MS/s × 2 components × 2 bit = 16 Mbit/s = 2 MB/s | arithmetic |
| Data rate, one 32-bit word per sample | 4 MS/s × 4 byte = 16 MB/s | arithmetic |
| CPU cycles per sample | CPU clock / 4 MS/s | CPU clock: `TODO` |
| PSRAM interface bandwidth and size | | `TODO` |

`TODO`: the CPU clock, the PSRAM interface bandwidth and the PSRAM size of the ESP32-C61 are
not read from the Espressif datasheet and are not quoted from memory. They are needed to
finish the cycles-per-sample and bandwidth comparison. The datasheet settles them.

What can be said without them:

- The 2 MB/s of 2-bit data is one eighth of the 16 MB/s that the capture hardware would write
  into the bank at 4 MS/s with one 32-bit word per sample. Whether the PSRAM interface
  sustains 2 MB/s is a `TODO` (see above).
- Whether the capture hardware can keep writing while the CPU reads another bank is not
  established. The firmware uses a single bank and a one-shot trigger.

## Conclusion

**Not possible with the current firmware. Whether it is possible with changed firmware is
not settled and needs a hardware test.**

Reasons:

1. The firmware captures one finite snapshot of at most 16380 words, 4.095 ms at 4 MS/s, and
   leaves the continuous gate off (`chip.h:28-29`, `receiver.c:146-148`).
2. A ring buffer with two alternating banks, on-the-fly 2-bit compression and copying to PSRAM
   needs a continuous or double-buffered capture mode, a way to follow the write position,
   PSRAM initialisation, and a new capture command and transfer format. None of these exists
   in the firmware, so each is a firmware change.
3. The hardware may support them, but the sources read here do not establish it. The
   ownership switch and the C5 comment suggest that continuous capture is not a simple
   change of one bit.

The stop condition of issue #13 applies: changing the firmware waits for the licence decision
in issue #7. A hardware test that would settle the open points (continuous gate on a C61, two
banks written alternately, noise folding at 4 MS/s) is a separate piece of work.

Open items, all `TODO` above: the band limiting before the clock division, the CPU clock, the
PSRAM bandwidth and size, and the behaviour of the continuous gate on the C61.
