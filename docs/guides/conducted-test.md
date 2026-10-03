# Conducted test (milestone M3)

In a conducted test the signal generator feeds the ESP32 through cables and attenuators.
**No signal is radiated.**

## Safety and regulations

- Never connect an antenna to the generator (HackRF or B210-class USRP). The RF path must be
  closed: cables and attenuators only.
- 2483.5–2500 MHz is shared with satellite services such as Globalstar. Transmitting from an
  antenna in this band needs a radio licence and can interfere with other receivers.
- Put the receiver in a metal enclosure if possible, to reduce leakage.
- HackRF: always keep the RF amplifier off (`-a 0`) and antenna-port power off (`-p 0`).
  `snappnt.io.generators.hackrf_transfer_cmd` always adds both.
- **Never connect a generator directly to the ESP32 without attenuators.** It can damage the
  ESP32 input.
- snappnt never starts a transmission. It only writes playback files and builds command lines
  for a person to check and run.
- Check the regulations that apply where you are; this page is not legal advice.

## Connection

```
B210-class USRP (TX) ─ 30 dB ─ splitter ─┬─ 30 dB ─ DC block ─ XIAO ESP32C3 (U.FL)
                                          └─ 30 dB ─ reference receiver (USRP)
```

- On the XIAO ESP32C3 the U.FL connector goes straight to the chip's LNA input, without an RF
  switch.
- The splitter sends the same signal to a reference receiver. If the reference receiver
  acquires the signal and the ESP32 does not, the problem is on the ESP32 side (capture, gain,
  or tuning).
- The attenuator values are a starting point. Begin with 60–70 dB in total.

## Input level and C/N0 calculator

`snappnt link-budget` adds up the losses between the generator and each receiver, and gives the
input level in dBm. It takes no default for the generator power, the losses or the ESP32 noise
figure, so each run states them; a path with no loss at all is given as `--loss 0`, and the
command refuses to run when a receiver's path has no loss option.
`--gen-dbm` is the power of the signal alone. When the playback file also contains
software-added noise, a power meter at the generator output reads signal plus noise, so that
reading must not be passed as `--gen-dbm`. The splitter's loss on each output is a value you pass: an
ideal 2-way split is 3.01 dB, and a real splitter adds some excess loss.

```bash
snappnt link-budget --gen-dbm -10 --loss att1=30 --loss splitter=3 --loss att2=30 \
    --loss dc_block=1 --esp32-nf-db 5 --scenario-cn0-dbhz 50
```

With these example values the input level is −10 − 30 − 3 − 30 − 1 = −74 dBm. A receiver noise
figure of 5 dB (an example, not a measured value) gives a noise density of −174 + 5 =
−169 dBm/Hz, so a noise-free signal would have C/N0 = −74 + 169 = 95 dB-Hz. This is the
weak-signal test of the section "Next step" below.

- `--scenario-cn0-dbhz` checks the software-noise test (step 1 of the procedure). The noise in
  the playback file has density N0_inj = P_in − C/N0 of the scenario. The command prints it
  next to the receiver's own noise density, and the C/N0 the receiver would actually see with
  both noises. The check passes when the injected noise is at least `--margin-db` above the
  receiver's noise. The default of 10 dB, which gives a C/N0 error of about 0.4 dB, is a
  choice made for this tool, not a value from a source (decision D-012). Exit code 1 means the
  check failed.
- `--esp32-loss` and `--ref-loss` list the losses on each branch after the splitter;
  `--ref-nf-db` turns on the reference receiver, and `--ref-loss` without it is an error. `--loss` is the part of the path shared by
  both.
- The noise density uses 290 K (−174 dBm/Hz plus the noise figure), the usual convention for
  noise figures. Signal power is the power in the received band; quantisation and filter losses
  inside the receiver are not included.
- TODO: the noise figures of the ESP32 and of the reference receiver are not verified. A bench
  measurement would settle them.

Record the inputs and results of each run in the
[conducted test log template](conducted-test-log-template.md).

## Procedure

1. **Write the playback file.**
   `snappnt sim scenarios/navic_s_conducted_gen.yaml --uhd --hackrf`
    - The file is one second long, which is 50 NavIC data symbols, so looping it does not cut a
      symbol in half at the loop point.
    - The carrier sits 1.5 MHz above the generator's centre frequency, so the generator's LO
      leakage (a spike at the centre) does not overlap the signal.
    - Noise is added in software, so the C/N0 is set by the scenario, not by the attenuators.
      Feed the ESP32 at a comfortable level, around −60 to −70 dBm.
2. **Set the generator's centre frequency.**
   2492.028 MHz − 1.5 MHz = 2490.528 MHz. The same value is written to `core:frequency` in the
   SigMF metadata.
3. **Transmit (a person does this by hand).**
   Build the command with `snappnt.io.generators.uhd_tx_cmd(...)` or
   `hackrf_transfer_cmd(...)`, read it, then run it.
4. **Capture with the XIAO.**
   `snappnt capture <port> --freq-hz 2492e6 -o out/run1`, see "Capturing with `snappnt capture`"
   below.
5. **Acquire.**
   `snappnt acquire <file> --signal navic_s_sps --prn 10 --freq-span 60000`
   The crystal errors of the ESP32 and the generator can add up to tens of kHz, so search
   widely.
6. **Vary C/N0 and compare.**
   Regenerate the playback file with different C/N0 values, measure the detection probability,
   and plot it over the simulated curve from `snappnt sweep scenarios/navic_s_esp32c3.yaml`.

## Capturing with `snappnt capture`

```bash
snappnt capture <serial port> --freq-hz 2492e6 --rate-sps 80e6 -n 16380 --count 5 -o out/run1
snappnt capture --dry-run --freq-hz 2492e6        # print the commands, send nothing
```

- The firmware tunes whole MHz only (100 to 6000). The remainder of the signal's carrier
  frequency (here 28 kHz for 2492.028 MHz) appears as a frequency offset in processing, so
  search widely in `snappnt acquire`.
- `--gain auto` (default) selects the hardware AGC (`GAIN HARDWARE`). `--gain <index>` sets
  `GAIN MANUAL <index>`. The firmware does not report the AGC gain it chose, so `snappnt:gain_index`
  is `null` in AGC mode.
- `--bandwidth-mhz` sets the analog bandwidth; without it the board's setting is unchanged.
  The firmware keeps the last setting while it is powered, including one made by another
  program such as the browser viewer. `snappnt capture` therefore sends `LPF?` immediately
  before every capture and records the reply in that recording. `snappnt:analog_bandwidth_mhz` holds a value only when `--bandwidth-mhz`
  was given; otherwise it is `null`, meaning the bandwidth in MHz is unknown, and the
  low-pass capacitor code in effect is in `snappnt:espsdr_lpf_code` (see
  `docs/design/espsdr-protocol.md`, "Analog low-pass setting"). Pass `--bandwidth-mhz` when
  the bandwidth matters for the recording.
  `--bits 8` uses the 8-bit transfer, `--bits 10` (default) the packed 10-bit transfer.
- The command refuses to start if any output file already exists; `--overwrite` replaces them.
  `--dry-run` prints the full sequence including the final `RELEASE`. It checks the frequency,
  the sample rate in the ESP-SDR rate table, the bandwidth (0, or 14 to 62 MHz) and the bit
  depth. The maximum gain index, the rates a particular chip offers and the maximum samples per
  capture are reported by the board (`LIMITS?`, `INFO`), so only a live run checks them. A file
  that cannot be written (for example a full disk) ends the run with exit code 1, naming the
  capture. Each recording is written under temporary names and renamed only when both files
  are complete, so a failed write leaves no partial files and an existing recording that
  `--overwrite` was meant to replace stays intact.
- With `--count N` greater than 1 each capture is its own recording, `run1_0000`, `run1_0001`,
  and so on (decision D-011). Captures already written stay if a later one fails; a damaged
  capture (wrong CRC-32) ends the run with exit code 1 after the port is resynchronised.
- Metadata in each `.sigmf-meta`: `core:hw` (`ESP-SDR` and the chip family), `snappnt:espsdr_info`
  (the firmware's `INFO` reply), `snappnt:host_time_utc` and `core:datetime`,
  `snappnt:gain_mode`, `snappnt:gain_index`, `snappnt:analog_bandwidth_mhz`,
  `snappnt:espsdr_lpf_reply`, `snappnt:espsdr_lpf_code`, `snappnt:espsdr_lpf_calibrated_codes`,
  `snappnt:espsdr_transfer_bits`, `snappnt:espsdr_capture_us`. The serial port name, host name,
  user name and output path are not recorded.
- **Not verified on hardware.** The command sequence follows the protocol page
  (`docs/design/espsdr-protocol.md`); verification is tracked in issue #11.

## Next step: a weak signal without added noise

Feeding a noise-free signal attenuated to around −130 dBm shows the real sensitivity,
including the ESP32's own noise figure and any noise folding at low sample rates. At this
level leakage from the generator matters, so use several attenuators in series and good
shielding.
