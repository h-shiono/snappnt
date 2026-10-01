"""Command line: ``snappnt <command> ...``

codes    print code properties (first chips in ICD octal form)
sim      scenario YAML -> SigMF (+ optional generator playback file)
acquire  SigMF -> acquisition table (and truth comparison if present)
sweep    scenario YAML -> detection probability vs C/N0 (CSV)
capture  ESP-SDR board on a serial port -> SigMF (one file per capture)
convert  raw I/Q file of UHD or HackRF -> SigMF
info     list signals and devices
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def _parse_range(text: str) -> list[float]:
    """'40:60:2' -> [40, 42, ..., 60]; '45,50' -> [45, 50]."""
    if ":" in text:
        a, b, s = (float(v) for v in text.split(":"))
        return list(np.arange(a, b + s / 2, s))
    return [float(v) for v in text.split(",")]


def _parse_prns(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def cmd_info(_: argparse.Namespace) -> int:
    from snappnt.frontend import list_devices
    from snappnt.signals import list_signals, load_signal

    print("signals:")
    for name in list_signals():
        s = load_signal(name)
        print(f"  {name:22s} {s.carrier_hz / 1e6:10.3f} MHz  {s.chip_rate_hz / 1e6:.3f} Mcps")
    print("devices:")
    for name in list_devices():
        print(f"  {name}")
    return 0


def cmd_codes(a: argparse.Namespace) -> int:
    from snappnt.signals import get_code, load_signal
    from snappnt.signals.codes.lfsr import first_chips_octal

    spec = load_signal(a.signal)
    prns = _parse_prns(a.prn) if a.prn else list(spec.prns())
    for prn in prns:
        c = get_code(spec, prn)
        octal = first_chips_octal(c)
        print(f"PRN {prn:3d}  length {c.size}  first10(octal) {octal}  sum {int(c.sum()):+d}")
    return 0


def cmd_sim(a: argparse.Namespace) -> int:
    from snappnt.io import write_sigmf
    from snappnt.signals import load_signal
    from snappnt.sim import generate, load_scenario
    from snappnt.sim.export import write_hackrf_int8, write_uhd_sc16

    scn = load_scenario(a.scenario)
    x, truth = generate(scn)
    spec = load_signal(scn.signal)
    out = Path(a.output or f"out/{scn.name}")
    base = write_sigmf(
        out,
        x,
        scn.receiver.sample_rate_hz,
        center_frequency_hz=spec.carrier_hz - scn.receiver.baseband_offset_hz,
        description=f"snappnt simulation: {scn.name}",
        truth=truth,
    )
    print(f"wrote {base}.sigmf-meta / .sigmf-data  ({x.size} samples)")
    if a.hackrf:
        p = write_hackrf_int8(x, base.with_name(base.name + ".hackrf.i8"))
        print(f"wrote {p}  (hackrf_transfer -t, int8 I/Q)")
    if a.uhd:
        p = write_uhd_sc16(x, base.with_name(base.name + ".uhd.sc16"))
        print(f"wrote {p}  (tx_samples_from_file --type short)")
    return 0


def cmd_acquire(a: argparse.Namespace) -> int:
    from snappnt.eval import is_correct
    from snappnt.io import get_truth, read_sigmf
    from snappnt.rx import acquire
    from snappnt.signals import load_signal

    x, meta = read_sigmf(a.file)
    fs = float(meta["global"]["core:sample_rate"])
    truth = get_truth(meta)
    signal = a.signal or (truth or {}).get("signal")
    if not signal:
        print("error: --signal is required (no truth annotation to read it from)", file=sys.stderr)
        return 2
    spec = load_signal(signal)
    center = (truth or {}).get("baseband_offset_hz", 0.0) if a.center is None else a.center
    prns = _parse_prns(a.prn) if a.prn else list(spec.prns())
    truth_by_prn = {s["prn"]: s for s in (truth or {}).get("satellites", [])}

    print(f"{spec.name}: {x.size} samples at {fs / 1e6:g} MSa/s ({x.size / fs * 1e3:.3f} ms)")
    print(" PRN  det  code[chip]   freq[Hz]   metric  thr    C/N0est  truth")
    for prn in prns:
        r = acquire(
            x, fs, spec, prn,
            center_offset_hz=center,
            freq_range_hz=(-a.freq_span, a.freq_span),
            n_blocks=a.blocks,
            pfa=a.pfa,
        )  # fmt: skip
        t = truth_by_prn.get(prn)
        mark = ""
        if t is not None:
            mark = "OK" if r.detected and is_correct(r, t, spec.code_length, 0.5) else "--"
        print(
            f" {prn:3d}  {'yes' if r.detected else ' no'}  {r.code_phase_chips:9.2f}  "
            f"{r.freq_offset_hz:9.0f}  {r.metric:7.1f}  {r.threshold:5.1f}  "
            f"{r.cn0_dbhz_est:6.1f}   {mark}"
        )
    return 0


def cmd_sweep(a: argparse.Namespace) -> int:
    from snappnt.eval import sweep, write_csv
    from snappnt.sim import load_scenario

    scn = load_scenario(a.scenario)
    pts = sweep(
        scn,
        _parse_range(a.cn0),
        a.trials,
        freq_range_hz=(-a.freq_span, a.freq_span),
        n_blocks=a.blocks,
        pfa=a.pfa,
        seed=a.seed,
    )
    print(" C/N0   Pd     Pwrong  metric")
    for p in pts:
        print(f" {p.cn0_dbhz:5.1f}  {p.p_detect:5.2f}  {p.p_wrong:5.2f}  {p.mean_metric:7.2f}")
    if a.output:
        print(f"wrote {write_csv(pts, a.output)}")
    return 0


def _parse_loss(text: str) -> float:
    """A loss in dB, written as `<dB>` or `<label>=<dB>`."""
    try:
        return float(text.rsplit("=", 1)[-1])
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a loss in dB: {text!r}") from None


def cmd_link_budget(a: argparse.Namespace) -> int:
    from snappnt.eval.linkbudget import evaluate_branches

    if a.ref_nf_db is None and a.ref_loss:
        print("error: --ref-loss needs --ref-nf-db", file=sys.stderr)
        return 2
    branches = {"ESP32": (a.esp32_loss or [], a.esp32_nf_db)}
    if a.ref_nf_db is not None:
        branches["reference"] = (a.ref_loss or [], a.ref_nf_db)
    for name, (own, _) in branches.items():
        if not (a.loss or own):
            print(
                f"error: no losses given for the {name} path; pass --loss, or --loss 0 "
                "if there really is none",
                file=sys.stderr,
            )
            return 2
    try:
        results = evaluate_branches(
            a.gen_dbm, a.loss or [], branches, a.scenario_cn0_dbhz, a.margin_db
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for r in results:
        print(f"[{r.name}]")
        print(f"  input level          {r.p_in_dbm:8.2f} dBm")
        print(f"  receiver NF          {r.nf_db:8.2f} dB (input)")
        print(f"  receiver noise       {r.noise_dbm_hz:8.2f} dBm/Hz")
        print(f"  C/N0, no added noise {r.cn0_dbhz:8.2f} dB-Hz")
        c = r.noise_check
        if c is not None:
            print(f"  injected noise       {c.injected_dbm_hz:8.2f} dBm/Hz")
            print(f"  injected - receiver  {c.ratio_db:8.2f} dB (margin {a.margin_db:.1f} dB)")
            print(f"  C/N0 at receiver     {c.effective_cn0_dbhz:8.2f} dB-Hz")
            print(f"  C/N0 error           {c.error_db:8.2f} dB")
            print(
                "  check                " + ("ok" if c.ok else "FAILED: receiver noise is too high")
            )
    if a.scenario_cn0_dbhz is not None and not all(r.noise_check.ok for r in results):
        return 1
    return 0


def cmd_capture(a: argparse.Namespace) -> int:
    from snappnt.io.espsdr_capture import (
        LIVE_ONLY_CHECKS,
        capture_paths,
        command_plan,
        existing_outputs,
        save_capture_sigmf,
        utc_now,
    )
    from snappnt.io.espsdr_client import (
        EspSdrClient,
        EspSdrDamagedCapture,
        EspSdrError,
        EspSdrTimeout,
    )

    gain = None if a.gain == "auto" else _parse_gain(a.gain)
    if gain == -1:
        print("error: --gain must be 'auto' or a non-negative integer index", file=sys.stderr)
        return 2
    try:
        plan = command_plan(
            frequency_hz=a.freq_hz,
            sample_rate_hz=a.rate_sps,
            n_samples=a.samples,
            gain=gain,
            bandwidth_mhz=a.bandwidth_mhz,
            bits=a.bits,
            count=a.count,
        )
        paths = capture_paths(a.output, a.count)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.dry_run:
        print("\n".join(plan))
        print(f"note: {LIVE_ONLY_CHECKS}", file=sys.stderr)
        return 0
    if not a.overwrite and (found := existing_outputs(paths)):
        print(
            f"error: {found[0]} exists (and {len(found) - 1} more); "
            "choose another --output or pass --overwrite",
            file=sys.stderr,
        )
        return 2
    if a.port is None:
        print("error: the serial port is required unless --dry-run is given", file=sys.stderr)
        return 2

    try:
        client = EspSdrClient(port=a.port)
    except (EspSdrError, EspSdrTimeout, OSError) as e:
        print(f"error: cannot open the board: {e}", file=sys.stderr)
        return 1
    done = 0
    try:
        info = client.info()
        client.tune(a.freq_hz)
        if a.bandwidth_mhz is not None:
            client.set_bandwidth_mhz(a.bandwidth_mhz)
        if gain is None:
            client.set_gain_hardware()
        else:
            client.set_gain_manual(gain)
        client.set_sample_rate(a.rate_sps)
        for path in paths:
            when = utc_now()
            cap = client.capture(a.samples, bits=a.bits)
            try:
                base = save_capture_sigmf(
                    cap,
                    path,
                    firmware_info=info,
                    gain=gain,
                    analog_bandwidth_mhz=a.bandwidth_mhz,
                    host_time_utc=when,
                    description="snappnt capture",
                )
            except OSError as e:
                print(f"error: cannot write capture {done + 1} of {a.count}: {e}", file=sys.stderr)
                return 1
            done += 1
            print(f"wrote {base}.sigmf-meta / .sigmf-data  ({cap.samples.size} samples)")
    except EspSdrDamagedCapture as e:
        print(f"error: damaged capture {done + 1} of {a.count}: {e}", file=sys.stderr)
        try:
            client.resync(99)
        except (EspSdrError, EspSdrTimeout):
            pass
        return 1
    except (EspSdrError, EspSdrTimeout, ValueError) as e:
        print(f"error: capture {done + 1} of {a.count}: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            client.release()
        except (EspSdrTimeout, OSError):
            pass
        client.close()
    return 0


def cmd_convert(a: argparse.Namespace) -> int:
    from snappnt.io import convert_iq

    try:
        base = convert_iq(
            a.input,
            a.output,
            a.format,
            a.rate_sps,
            a.freq_hz,
            a.device,
            description=a.description,
            overwrite=a.overwrite,
        )
    except (ValueError, FileExistsError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"wrote {base}.sigmf-meta / .sigmf-data")
    return 0


def _parse_gain(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        return -1
    return value if value >= 0 else -1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="snappnt", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("info", help="list signals and devices")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("codes", help="print spreading-code properties")
    s.add_argument("--signal", default="navic_s_sps")
    s.add_argument("--prn", help="e.g. 1-14 or 1,5,9 (default: all)")
    s.set_defaults(func=cmd_codes)

    s = sub.add_parser("sim", help="generate a snapshot from a scenario")
    s.add_argument("scenario")
    s.add_argument("-o", "--output", help="output base path (default out/<scenario name>)")
    s.add_argument("--hackrf", action="store_true", help="also write int8 file for hackrf_transfer")
    s.add_argument("--uhd", action="store_true", help="also write sc16 file for UHD playback")
    s.set_defaults(func=cmd_sim)

    for name, func, helptext in (
        ("acquire", cmd_acquire, "acquire PRNs in a SigMF recording"),
        ("sweep", cmd_sweep, "detection probability vs C/N0"),
    ):
        s = sub.add_parser(name, help=helptext)
        if name == "acquire":
            s.add_argument("file", help="SigMF base path, .sigmf-meta or .sigmf-data")
            s.add_argument("--signal")
            s.add_argument("--prn")
            s.add_argument("--center", type=float, help="carrier offset in baseband [Hz]")
        else:
            s.add_argument("scenario")
            s.add_argument("--cn0", default="40:60:2", help="start:stop:step or list [dB-Hz]")
            s.add_argument("--trials", type=int, default=20)
            s.add_argument("--seed", type=int, default=0)
            s.add_argument("-o", "--output", help="CSV path")
        s.add_argument("--freq-span", type=float, default=50e3, help="search +/- [Hz]")
        s.add_argument("--blocks", type=int, default=1, help="non-coherent blocks")
        s.add_argument("--pfa", type=float, default=1e-3)
        s.set_defaults(func=func)

    s = sub.add_parser("link-budget", help="input level and C/N0 for a conducted test")
    s.add_argument(
        "--gen-dbm",
        type=float,
        required=True,
        help="generator output of the signal alone, without added noise [dBm]",
    )
    s.add_argument(
        "--loss",
        type=_parse_loss,
        action="append",
        metavar="[LABEL=]DB",
        help="loss shared by both receivers [dB], repeatable",
    )
    s.add_argument(
        "--esp32-loss",
        type=_parse_loss,
        action="append",
        metavar="[LABEL=]DB",
        help="loss on the ESP32 branch only (splitter output, attenuator, DC block) [dB]",
    )
    s.add_argument("--esp32-nf-db", type=float, required=True, help="ESP32 noise figure [dB]")
    s.add_argument(
        "--ref-loss",
        type=_parse_loss,
        action="append",
        metavar="[LABEL=]DB",
        help="loss on the reference receiver branch only [dB]",
    )
    s.add_argument("--ref-nf-db", type=float, help="reference receiver noise figure; enables it")
    s.add_argument("--scenario-cn0-dbhz", type=float, help="C/N0 set in software, to check")
    s.add_argument("--margin-db", type=float, default=10.0, help="required noise ratio [dB]")
    s.set_defaults(func=cmd_link_budget)

    s = sub.add_parser("capture", help="capture snapshots from an ESP-SDR board to SigMF")
    s.add_argument("port", nargs="?", help="serial port (not needed with --dry-run)")
    s.add_argument("--freq-hz", type=float, default=2492e6, help="whole MHz, 100 to 6000")
    s.add_argument("--rate-sps", type=float, default=80e6)
    s.add_argument("-n", "--samples", type=int, default=16380)
    s.add_argument("--gain", default="auto", help="'auto' (hardware AGC) or a gain index")
    s.add_argument("--bandwidth-mhz", type=float, help="analog bandwidth (default: unchanged)")
    s.add_argument("--count", type=int, default=1, help="number of captures, one file each")
    s.add_argument("-o", "--output", default="out/capture", help="output base path")
    s.add_argument("--bits", type=int, choices=(8, 10), default=10)
    s.add_argument("--overwrite", action="store_true", help="replace existing output files")
    s.add_argument("--dry-run", action="store_true", help="print the commands, send nothing")
    s.set_defaults(func=cmd_capture)

    s = sub.add_parser("convert", help="convert a raw UHD or HackRF I/Q file to SigMF")
    s.add_argument("input", help="raw interleaved I/Q file")
    s.add_argument("-o", "--output", required=True, help="output base path")
    s.add_argument(
        "--format",
        required=True,
        choices=("uhd-short", "uhd-float", "hackrf"),
        help="uhd-short: int16 and uhd-float: float32 (both little endian, as written on x86 "
        "and ARM hosts); hackrf: signed int8",
    )
    s.add_argument("--rate-sps", type=float, required=True, help="sample rate of the recording")
    s.add_argument("--freq-hz", type=float, required=True, help="centre frequency [Hz]")
    s.add_argument("--device", required=True, help="recording device, stored in core:hw")
    s.add_argument("--description", default="", help="free text stored in core:description")
    s.add_argument("--overwrite", action="store_true", help="replace existing output files")
    s.set_defaults(func=cmd_convert)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
