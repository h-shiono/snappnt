# ESP-SDR serial protocol

This page describes how a host program talks to the ESP-SDR firmware over a serial link,
as read from the firmware and browser-client sources. It is the basis for
`src/snappnt/io/espsdr_client.py` and `src/snappnt/io/espsdr_capture.py`.

**Status: read from source.** On an ESP32-C3 (Seeed XIAO ESP32C3), the following were checked
on hardware in [ESP32-C3 bench checks without an RF source](../results/esp32c3-bench-no-rf.md)
(issue #41): the replies to `INFO`, `CAPS`, `LIMITS?`, `RANGE?`, `TRANSPORT?`, `GAIN?` and
`FREQ 2492`; the maximum of 16380 samples per capture (16381 is rejected); the `CAP20` header,
payload length and CRC-32; and the sign of frequency (the spectrum is not mirrored). Everything
else on this page, and every other chip, has not been verified on hardware. Further hardware
verification is tracked in issue #11.

## Sources and how to read the citations

Every statement carries a citation of the form `file:line`. Line numbers refer to these
commits:

| Short name | Repository | Commit |
|---|---|---|
| `fw` | <https://github.com/ESPARGOS/esp-sdr> (firmware) | `4935ac29f7baabd552084534b2a346669937d981` |
| `web` | <https://github.com/ESPARGOS/esp-web-sdr> (browser client) | `88958cced090b0b029cf46ed6c02b256692a6fef` |

The firmware is licensed GPL-3.0-or-later (`fw` `README.md:143-146`); its README says that
the capture mechanism may be implemented independently under any licence
(`fw` `README.md:158-160`). The snappnt client was written from the protocol description
below, not from copied code. Whether snappnt may reuse the firmware or browser-client code
is decided in issue #7.

Each chip has its own receiver file. The ESP32-C3 file `fw` `main/targets/esp32c3/receiver.c`
is read in full, because it is snappnt's first target; the other chips are cited only where
they differ. Terms: *sample* is one complex I/Q pair; *rate index* is the second argument of
a capture command; *word* is one 32-bit entry of the chip's capture memory.

## Transport

- Newline-terminated ASCII commands, text replies; capture replies are followed by a binary
  payload (`fw` `README.md:52-55`).
- UART default 2,000,000 baud, 8 data bits, no parity, 1 stop bit, no flow control
  (`fw` `main/common/burst_serial.c:22`, `:80-86`). On native USB Serial/JTAG the baud
  setting does not apply: `TRANSPORT?` reports baud 0 and `BAUD` is answered with
  `ERR baud_transport` (`fw` `main/common/burst_serial.c:67`, `:101-102`;
  `web` `radio.js:83`).
- The firmware ignores carriage returns, ignores empty lines, and accepts at most 127
  characters per command line (`fw` `main/common/burst_serial.c:25`, `:134-139`, `:145`).
  A longer line is answered with `ERR command_length` (`fw` `main/targets/esp32c3/receiver.c:230`).
- A partly received line is discarded after 3 s without a byte
  (`fw` `main/common/burst_serial.c:125-128`).
- One client controls the radio at a time. A second port gets `ERR busy` while the first
  holds it. The hold ends with `RELEASE` (reply `OK`) or after 5 s without a command
  (`fw` `main/targets/esp32c3/receiver.c:225-239`).
- A client must read a complete reply, including the binary payload, before sending the next
  command (`fw` `README.md:68`). After an incomplete transfer, `SYNC <nonce>` is echoed as
  `SYNC <nonce>`, which lets the client find the end of stale bytes
  (`fw` `main/targets/esp32c3/receiver.c:157-159`;
  client side `web` `radio.js:14-29`).
- Opening a UART bridge can reset the board, and a command sent during boot is lost. The
  browser client therefore sends a blank line plus `SYNC <time>` up to three times until it
  sees its marker echoed (`web` `radio.js:14-29`). `EspSdrClient` does the same when it opens
  a port (nonces 1, 2, 3), and accepts an echo that follows stale bytes on the same line.
- Reply timeouts: the browser client allows 5 s for a header line and 5 s for the payload,
  with a 500 ms idle limit inside the payload (`web` `radio.js:12`, `:177`).

## Commands (ESP32-C3 firmware)

All command words are upper case. Numbers are unsigned decimal integers. A command that
does not parse, or whose numbers are out of range, is answered with `ERR command`
(`fw` `main/targets/esp32c3/receiver.c:194`).

| Command | Reply | Meaning | Source |
|---|---|---|---|
| `INFO` | `C3SDR 6 burst 16380` | Chip family, protocol number 6, maximum samples per capture | `receiver.c:188` |
| `CAPS` | `CAPS UARTBAUD RXLIMITS SERIALLEASE [DUALSERIAL] TUNEEXT LPFANA GAIN HWAGC IQ8` | Capability words (newer firmware adds `SPEC SPECN SPECCAPS SPECSTAT DCT` at the start; see below the table) | `receiver.c:168-174` |
| `LIMITS?` | `LIMITS {"gain":[0,<max>,1],"bandwidth":[14,62,1,0],"rates":[80000000],"bits":[8,10]}` | Receive limits as JSON | `main/common/burst_limits.h:4-32` |
| `RANGE?` | `RANGE 100 6000 1` | Tuning range in MHz and step | `receiver.c:185-187`, `main/common/rx_tuning.h:5-7` |
| `TRANSPORT?` | `TRANSPORT USB 0` or `TRANSPORT UART <baud>` | Active interface | `receiver.c:146-151` |
| `FREQ <MHz>` | `OK` | Tune to a whole number of MHz | `receiver.c:189-190` |
| `BANDWIDTH <MHz>` | `OK` | Analog bandwidth, 0 = widest | `receiver.c:175-178` |
| `GAIN MANUAL <index>` / `GAIN HARDWARE` / `GAIN?` | `OK` / `OK` / `GAIN <mode> <index> 0 <max> <flag>` | Gain control | `main/common/burst_gain.h:46-56` |
| `CAP16 <n> <rate-index>` | `DATA ...` then payload | 8-bit capture | `receiver.c:156`, `:191-193` |
| `CAP20 <n> <rate-index>` | `DATA ...` then payload | 10-bit packed capture | `receiver.c:191-193` |
| `CAP <n> <rate-index>` | `DATA ...` then payload | Raw 32-bit words | `receiver.c:191-193` |
| `RXRUN <n> <rate-index> <repeats> <16\|20>` | repeated `DATA ...`, then `END` | Repeated captures, 1 to 1000 | `receiver.c:160-167` |
| `SYNC <nonce>` | `SYNC <nonce>` | Resynchronise | `receiver.c:157-159` |
| `RELEASE` | `OK` | Free the radio | `receiver.c:232-234` |
| `BAUD?` / `BAUD <1000000\|2000000>` | `BAUD <rate>` / `OK BAUD <rate>` | UART only | `main/common/burst_serial.c:39-69` |

Other commands exist (`LPF`, `LPF?`, `LPF AUTO`, `receiver.c:179-184`) and are not used by
snappnt. In the C3 receiver source and the shared files, no command transmits: the only
transmit-related calls turn transmission off while preparing reception
(`receiver.c:72-74`). The firmware README says the same (`fw` `README.md:21-22`). snappnt
therefore implements no transmit command.

Newer firmware adds on-chip spectrum commands. At commit
`550fadea4d00a9e26ce921c5832167becb3dc20c` (2026-10-01) the C3 receiver answers `CAPS` with
`CAPS SPEC SPECN SPECCAPS SPECSTAT DCT UARTBAUD ...` (`main/targets/esp32c3/receiver.c:217`)
and passes each command line to the spectrum and ring-capture handlers before the commands
in the table above (`receiver.c:189`, `:193`). These commands were not read for this page and
are not used by snappnt. The capture path that `CAP16` and `CAP20` use was only moved into a
separate function between `4935ac2` and `550fade`; the `DATA` header format is the same
(`receiver.c:151-159` at `550fade`). The ESP32-C3 firmware
checked on hardware answered `CAPS` with these words
([ESP32-C3 bench checks](../results/esp32c3-bench-no-rf.md)).

## Setting the frequency

- Command `FREQ <MHz>`. The argument is a whole number of MHz from 100 to 6000. Fractional
  values and values outside that range are answered with `ERR command`
  (`receiver.c:189`, `main/common/rx_tuning.h:5-10`; `fw` `docs/rx-controls.md:60-62`).
- The command is accepted without checking that the PLL locks
  (`fw` `docs/rx-controls.md:62-64`). The firmware's own README calls the extended range
  "software attempt limits" that "have not been hardware validated" (`fw` `README.md:123-124`).
- A frequency that is a Wi-Fi channel centre (2412 to 2472 MHz in 5 MHz steps, or 2484 MHz)
  is set through the normal channel call. Any other frequency is calibrated on 2412 MHz and
  then programmed directly (`receiver.c:56-63`). So `FREQ 2492` (the NavIC S-band centre,
  2492.028 MHz) is accepted as 2492 MHz and the 28 kHz remainder is not tunable; it has to
  be handled as a frequency offset in processing.
- The frequency is applied immediately, and the command replies `OK` after the radio has been
  prepared (`receiver.c:190`).
- The browser client sends `FREQ` only when the frequency changed (`web` `radio.js:161`).

## Setting the sample rate

There is no separate sample-rate command. The rate is the second argument of each capture
command, as an index (`fw` `README.md:64-65`):

| Rate index | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| Nominal rate (MS/s) | 80 | 40 | 20 | 10 | 8 | 4 | 16 |

The same table is in the browser client (`web` `radio.js:194`, the `divider` lookup).

Which indices a chip accepts is chip specific:

- **ESP32-C3: only index 0 (80 MS/s).** Any other index from 1 to 6 passes the command check
  but is answered with `ERR rate` and no payload (`receiver.c:107`; `LIMITS?` lists only
  `80000000`, `fw` `main/common/burst_limits.h:24-25`). The browser client agrees
  (`web` `radio.js:111`).
- ESP32: indices 0, 1 and 6 (80, 40 and 16 MS/s) (`fw` `main/targets/esp32/receiver.c:163`).
- ESP32-S2 and ESP32-S3: indices 0, 1 and 6 (`fw` `main/targets/esp32s2/receiver.c:134`,
  `main/targets/esp32s3/receiver.c:128`).
- ESP32-C6: index 0 only (`fw` `main/families/c5_c6_c61/receiver.c:253`, `:313`).
- ESP32-C5 and ESP32-C61: indices 0 to 5 (same lines).
- ESP32-S31: index 0 to the number of rates in its own table
  (`fw` `main/targets/esp32s31/receiver.c:238`); the browser client lists 16, 8 and 4 MS/s
  for it (`web` `radio.js:111`).
- All rates are nominal. The README states that captures have gaps and that sample-clock
  accuracy is not calibrated (`fw` `README.md:135-136`, `docs/rx-controls.md:93-94`).

Consequence for snappnt: the ESP32-C3 delivers only 80 MS/s snapshots; lower rates need the
ESP32-C61 (indices 1 to 5). This matches `sample_rates_sps` in
`src/snappnt/frontend/devices/esp32c3.yaml`.

## Capture request

```text
CAP16 <n> <rate-index>      8-bit I and Q
CAP20 <n> <rate-index>      10-bit I and Q, packed
CAP   <n> <rate-index>      raw 32-bit words
```

- `n` is the number of samples. The C3 accepts 256 to 16380 (`receiver.c:25`, `:193`).
  Anything else is `ERR command`.
- The firmware turns `CAP16` into `CAP20` with a flag that selects 8-bit output
  (`receiver.c:156`). The reply format is therefore identical except for the payload.
- Before the capture the C3 prepares the receiver (if not already done), fills the capture
  memory with a marker word, applies the analog bandwidth setting, and starts the capture
  with interrupts disabled (`receiver.c:106-131`). The capture takes about 205 µs at the
  maximum sample count (`receiver.c:112-113`).
- If the capture does not finish within 20 ms, the reply is `ERR capture_timeout`
  (`receiver.c:125`, `:133`). If any word still holds the marker, the reply is
  `ERR capture_incomplete` (`receiver.c:134-136`). Other chips have additional errors
  (`capture_overrun`, `capture_memory <index>`, `capture_settings`, `args`;
  see the `ERR` lines in `fw` `main/families/c5_c6_c61/receiver.c:173-178`,
  `main/targets/esp32/receiver.c:82`, `:107`, `:112`).
- Replies to every command are one line, `OK` or a data header, or `ERR <reason>`
  (`fw` `README.md:68-69`). The reason is a short word, optionally followed by a number.
- The typical host sequence is (`web` `radio.js:194`):
  `FREQ <MHz>` → `BANDWIDTH <MHz>` (only if a bandwidth is wanted) → `GAIN ...` → `GAIN?`
  → `CAP20 <n> <rate-index>`. snappnt sends the gain commands only when asked to.

## Data sent to the host

The reply is the header line

```text
DATA <n> <crc32-hex> <capture-microseconds>\n
```

followed immediately by the payload (`receiver.c:141-142`).

- `<n>` echoes the number of samples. The browser client rejects a reply whose `n` differs
  (`web` `radio.js:173-174`).
- `<crc32-hex>` is eight lower-case hexadecimal digits, the CRC-32 of the payload bytes
  (`receiver.c:139-141`). The browser client computes the standard reflected CRC-32 with
  polynomial `0xEDB88320`, initial value `0xFFFFFFFF` and final inversion
  (`web` `radio.js:3-4`) and compares it with this field (`web` `radio.js:178`), so
  `zlib.crc32` of the payload is the expected value. That the firmware routine
  `esp_rom_crc32_le(0, ...)` is the same CRC is inferred from the browser client working
  against it. On an ESP32-C3, `zlib.crc32` of the payload matched the header in every `CAP20`
capture of [ESP32-C3 bench checks](../results/esp32c3-bench-no-rf.md) (more than 300).
- `<capture-microseconds>` is the time the firmware measured around the capture, including
  setup of the capture hardware (`receiver.c:116`, `:127`). It is not the sample duration.

### Payload size and layout

| Command | Payload bytes | Source |
|---|---|---|
| `CAP16` | `2 n` | `receiver.c:102-104`, `:95-100` |
| `CAP20` | `ceil(20 n / 8)` | `receiver.c:81`, `:102-104` |
| `CAP` | `4 n` | `receiver.c:102-104` |

There is no per-payload header and no trailer; the CRC is in the header line.

**10-bit packed (`CAP20`).** Each sample is the low 20 bits of one capture word. The firmware
writes them as a little-endian bit stream: sample 0 occupies bits 0 to 19, sample 1 bits 20
to 39, and so on, with the least significant bit of each byte first
(`receiver.c:82-91`; decoded the same way in `web` `radio.js:193`, and in its test
`web` `tests/radio-c3.test.mjs:31-35`). Two samples take five bytes; an odd last sample
takes three bytes (`receiver.c:82`). Within a 20-bit field, bits 0 to 9 are one component
and bits 10 to 19 the other, each signed 10-bit two's complement
(`web` `radio.js:193`: `i=w&1023`, `q=w>>>10`).

**8-bit (`CAP16`).** Two bytes per sample, signed two's complement. The first byte is
bits 9 to 2 of the word's low field (the upper eight bits of the 10-bit value) and the
second byte is bits 19 to 12 (the upper eight bits of the other field)
(`receiver.c:95-100`). The low two bits are dropped by arithmetic truncation. The browser
client multiplies by 4 to return to the 10-bit scale (`web` `radio.js:193`).

**Raw (`CAP`).** The words as stored in the chip's memory. The byte order is not stated in
the source; the chip is little-endian RISC-V, so little-endian is assumed (an assumption).
snappnt does not use this format.

### Which component is I

The firmware names no component I or Q. The browser client reads the low 10-bit field as
I and the high 10-bit field as Q, and then **negates Q** before display
(`web` `radio.js:193`: `iq[2*j+1]=-q/512`). That is, the browser client displays `low − j·high`.

`espsdr_iq.unpack_words` (written earlier from the ESP-SDR documentation) reads the high
field as I and the low field as Q, so its result is `high + j·low`, which equals
`j · (low − j·high)`: the browser client's signal multiplied by the constant `j`. A constant
factor changes only the carrier phase, which neither acquisition nor the CRC depends on, and
it does not change the sign of frequency. snappnt keeps its existing convention. On an
ESP32-C3 the spectrum from `unpack_words` is not mirrored: a positive baseband frequency is a
radio frequency above the tuned frequency
([ESP32-C3 bench checks](../results/esp32c3-bench-no-rf.md), "Sign of frequency").

### Maximum samples per capture

The number in the `INFO` reply is the maximum; the client reads it and may not ask for more.

| Chip | Maximum `n` | Source |
|---|---|---|
| ESP32-C3 | 16380 | `fw` `main/targets/esp32c3/receiver.c:25`, `:188` |
| ESP32-C5, C6, C61 | 16380 | `fw` `main/targets/esp32c5/chip.h:4`, `esp32c6/chip.h:4`, `esp32c61/chip.h:3` |
| ESP32-S3 | 16380 | `fw` `main/targets/esp32s3/receiver.c:26` |
| ESP32-S31 | 16380 | `fw` `main/targets/esp32s31/receiver.c:248` |
| ESP32 | 16380 (reply of `INFO`) | `fw` `main/targets/esp32/receiver.c:173` |
| ESP32-S2 | 12284 | `fw` `main/targets/esp32s2/receiver.c:27` |

The minimum is 256 samples on every chip (`receiver.c:193`, `esp32/receiver.c:163`).
The browser client accepts an `INFO` maximum from 4096 to 16384
(`web` `radio.js:109`). The C3 value 16380 is below the 16384 that
`max_capture_samples` in `esp32c3.yaml` assumes: 16380 words of 4 bytes fit in the 64 KiB
bank at `0x3fcb0000` (`receiver.c:21-26`). The yaml file is outside the scope of the
issue that produced this page and is left unchanged.

At 80 MS/s, 16380 samples last 204.75 µs, equal to about 0.2 of one NavIC code period of
1 ms. The firmware's own comment gives "about 205 µs" (`receiver.c:112-113`).

## Behaviour that matters for snapshots

- Each capture is a separate burst. The radio does not stream; between captures there are
  gaps while the data are sent (`fw` `README.md:135`).
- Gain is hardware AGC by default (`fw` `README.md:115`; `main/common/burst_gain.h:12`). The gain
  index in the old 32-bit word format is not part of the packed payload.
- Gain and power are uncalibrated (`fw` `README.md:136`).

## Error replies and failures the client handles

| Situation | What the client does |
|---|---|
| Reply begins with `ERR ` | Raise an error that carries the reply text |
| No reply within the timeout | Raise a timeout error; the caller may send `SYNC` |
| Header does not match `DATA <n> <hex> <us>` or `n` differs | Raise a damaged-capture error |
| Payload shorter than expected | Raise a damaged-capture error |
| CRC-32 of payload differs from header | Raise a damaged-capture error |

The browser client retries up to six times with half the sample count after a damaged
capture (`web` `radio.js:168`, `:187`). snappnt does not retry; the caller decides.
