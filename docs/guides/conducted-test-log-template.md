# Conducted test log template

Copy this page's text into a file outside the repository, or into an issue comment, and fill it
in for each conducted test run (see [Conducted test](conducted-test.md)).

**Public-safety reminder.** Do not record serial numbers of instruments, locations, host names,
user names or file paths from your machine ([Public-safety rules](../development/public-safety.md)).
Give equipment by model only.

```text
Date (UTC):
Run name:

Equipment (model only)
  Generator:
  Receiver under test (board and chip):
  Reference receiver:
  Splitter:
  DC block:
  Enclosure / shielding:

Path
  Attenuators in series, ESP32 branch (dB each):
  Attenuators in series, reference branch (dB each):
  Splitter loss per output (dB, measured or assumed):
  Cable losses (dB, measured or assumed):

Generator settings
  Centre frequency (MHz):
  Sample rate (sps):
  Output power setting (dBm):
  Amplifier / antenna-port power state (HackRF: both off):
  Playback file name:

Scenario
  Scenario file:
  PRN:
  C/N0 set in software (dB-Hz), or "none" for the weak-signal test:

ESP32 capture
  Frequency (MHz):
  Sample rate (sps):
  Gain mode and index:
  Recorded file names:

Calculator (snappnt link-budget)
  Command line:
  Input level, ESP32 branch (dBm):
  Input level, reference branch (dBm):
  Noise figures used (dB) and where they come from:
  Injected noise minus receiver noise (dB) and check result:
  C/N0 at the receiver (dB-Hz):

Results
  Acquired on the reference receiver (yes/no):
  Acquired on the ESP32 (yes/no, code phase, frequency offset):

Notes:
```
