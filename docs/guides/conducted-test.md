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
   Requires the ESP-SDR client (issue #6) and the `snappnt capture` command (issue #8).
5. **Acquire.**
   `snappnt acquire <file> --signal navic_s_sps --prn 10 --freq-span 60000`
   The crystal errors of the ESP32 and the generator can add up to tens of kHz, so search
   widely.
6. **Vary C/N0 and compare.**
   Regenerate the playback file with different C/N0 values, measure the detection probability,
   and plot it over the simulated curve from `snappnt sweep scenarios/navic_s_esp32c3.yaml`.

## Next step: a weak signal without added noise

Feeding a noise-free signal attenuated to around −130 dBm shows the real sensitivity,
including the ESP32's own noise figure and any noise folding at low sample rates. At this
level leakage from the generator matters, so use several attenuators in series and good
shielding.
