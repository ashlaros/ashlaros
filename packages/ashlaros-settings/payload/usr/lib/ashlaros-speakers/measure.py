#!/usr/bin/env python3
"""Measure a speaker with a microphone and fit peaking filters to flatten it.

The DSP half of ashlaros-speakers (#92). The shell front end owns the
devices, the prompts and playing and recording through pw-play and
pw-record; this owns the maths and the filter-chain file it produces, so
there is nothing here that touches the audio stack.

    measure.py sweep OUT.raw CHANNELS INDEX
        the test signal, f32 at 48 kHz: CHANNELS interleaved, the sweep in
        channel INDEX (0-based) and silence in the others
    measure.py fit SINK LABEL POSITION=REC.raw[,REC.raw...]...
        mono f32 captures, one or more per channel position (FL, FR, ...),
        averaged; prints the filter-chain drop-in, and a report on stderr
    measure.py selftest
        the fit against synthetic speakers

The method is the usual one and deliberately no more: an exponential sweep
(Farina), deconvolved by regularised FFT division, smoothed to 1/6 octave,
and flattened by placing one RBJ peaking filter at a time on the largest
remaining deviation. omarchy-speaker-calibrator does this with 10,890
lines and scipy; this does the part that makes laptop speakers stop
booming, with numpy alone.

ponytail: the greedy fit places each filter where the deviation is largest
and never revisits it. If a result is audibly short of flat, the next step
is a joint least-squares refinement of all bands, not more bands.
"""

import re
import sys

import numpy as np

RATE = 48000
# 50 Hz to 16 kHz covers what a laptop or desk speaker reproduces at all;
# below 50 Hz there is nothing to measure, and correcting there only drives
# a small driver into distortion
F_LOW, F_HIGH = 50.0, 16000.0
# Never fitted outside this band, and inside it only where the speaker
# plays at all: see fit_band
FIT_LOW, FIT_HIGH = 100.0, 12000.0
# Below the level the speaker plays at, by this much and all the way to the
# end of the range, is roll-off rather than a dip
ROLLOFF_DB = -6.0
SWEEP_SECONDS = 4.0
LEAD_SECONDS = 0.5  # silence before, so the capture starts in room noise
TAIL_SECONDS = 1.0  # silence after, for the room and the capture latency
LEVEL = 0.5  # -6 dBFS, into a speaker the front end sets to a fixed volume
# A digital microphone clicks as it opens: on a ThinkPad Z13 the first 10 ms
# of every capture were at full scale. The capture starts well inside the
# sweep's lead silence, so this much of it is dropped rather than measured.
SETTLE_SECONDS = 0.1
# The sweep has to stand clear of the room: measured on the same laptop, at
# 40 % volume it was 4 dB above the noise, at 70 % 30 dB
MIN_SNR_DB = 15.0

MAX_FILTERS = 6
MAX_CUT_DB = 12.0
# Boosts stay small: a dip is often a room null or a cancellation at the
# microphone position, which a boost cannot fill and only makes louder
# everywhere else
MAX_BOOST_DB = 4.0
STOP_DB = 2.0  # under the measurement's own spread, a filter only adds noise
# Broad filters only, and few of them. Measured on a ThinkPad Z13, three
# sweeps back to back agree within 0.9 dB, but the same speaker measured
# minutes apart moves by 2 dB rms and up to 10 dB at one frequency: narrow
# features are not the speaker, they are the moment. Fitted with Q up to 4
# they came back as new faults in the next measurement; 2.5 and a third of
# an octave of smoothing leave only what holds still.
Q_MIN, Q_MAX = 0.7, 2.5


def sweep():
    """The exponential sweep, with its lead and tail silence."""
    n = int(SWEEP_SECONDS * RATE)
    t = np.arange(n) / RATE
    k = np.log(F_HIGH / F_LOW)
    s = np.sin(2 * np.pi * F_LOW * SWEEP_SECONDS / k * (np.exp(t * k / SWEEP_SECONDS) - 1))
    # 20 ms fades, so the ends do not click - a click is broadband and would
    # be measured as the speaker
    fade = int(0.02 * RATE)
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, fade))
    s[:fade] *= ramp
    s[-fade:] *= ramp[::-1]
    lead = np.zeros(int(LEAD_SECONDS * RATE))
    tail = np.zeros(int(TAIL_SECONDS * RATE))
    return (LEVEL * np.concatenate([lead, s, tail])).astype(np.float32)


def delay(played, recorded):
    """Samples by which the capture lags the playback, by FFT cross-correlation."""
    n = 1 << int(np.ceil(np.log2(len(played) + len(recorded))))
    xc = np.fft.irfft(np.fft.rfft(recorded, n) * np.conj(np.fft.rfft(played, n)), n)
    # only non-negative lags: the capture cannot hear the sweep before it plays
    return int(np.argmax(np.abs(xc[: len(recorded)])))


def response(played, recordings):
    """Magnitude response in dB on a log grid, smoothed to a third of an octave.

    Each recording is deconvolved on its own and their power averaged, so
    a sound in the room during one sweep counts for a third of it. Returns
    (frequencies, dB). The absolute level is arbitrary - the stream volume,
    the microphone gain - so it is normalised to the fit band's median
    before anything reads it.
    """
    n = 1 << int(np.ceil(np.log2(2 * len(played))))
    x = np.fft.rfft(played, n)
    # Regularised division: where the sweep put no energy, the ratio is
    # noise, and eps keeps it from being enormous noise
    eps = 1e-3 * np.max(np.abs(x)) ** 2
    # Keep 300 ms of the impulse response: the speaker and the early room.
    # Later reflections are what the listener's room does, not the speaker,
    # and a filter cannot correct them from one microphone position.
    keep = int(0.3 * RATE)
    window = np.ones(keep)
    window[-keep // 4 :] = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, keep // 4))
    power = np.zeros(n // 2 + 1)
    for recorded in recordings:
        lag = delay(played, recorded)
        aligned = recorded[lag : lag + len(played)]
        aligned = np.pad(aligned, (0, len(played) - len(aligned)))
        h = np.fft.rfft(aligned, n) * np.conj(x) / (np.abs(x) ** 2 + eps)
        ir = np.fft.irfft(h, n)
        power += np.abs(np.fft.rfft(ir[:keep] * window, n)) ** 2
    freqs = np.fft.rfftfreq(n, 1 / RATE)

    grid = np.geomspace(F_LOW, F_HIGH, 240)
    smoothed = np.empty_like(grid)
    for i, f in enumerate(grid):
        band = (freqs >= f * 2 ** (-1 / 6)) & (freqs <= f * 2 ** (1 / 6))
        smoothed[i] = np.mean(power[band])
    db = 10 * np.log10(smoothed + 1e-20)
    fit = (grid >= FIT_LOW) & (grid <= FIT_HIGH)
    return grid, db - np.median(db[fit])


def peaking_db(freqs, fc, gain, q):
    """An RBJ peaking biquad's magnitude in dB - PipeWire's bq_peaking."""
    a = 10 ** (gain / 40)
    w0 = 2 * np.pi * fc / RATE
    alpha = np.sin(w0) / (2 * q)
    b = np.array([1 + alpha * a, -2 * np.cos(w0), 1 - alpha * a])
    den = np.array([1 + alpha / a, -2 * np.cos(w0), 1 - alpha / a])
    z = np.exp(-1j * 2 * np.pi * freqs / RATE)
    num = b[0] + b[1] * z + b[2] * z * z
    dnm = den[0] + den[1] * z + den[2] * z * z
    return 20 * np.log10(np.abs(num / dnm))


def fit_band(grid, db):
    """The band a speaker actually plays, from its own measurement.

    A small speaker rolls off below a few hundred hertz, and that is the
    driver, not a fault: measured on a ThinkPad Z13, the left speaker is
    15-21 dB down from 60 to 200 Hz. A fit that treats that as a dip
    stacks boosts there - six of its ten filters, before this - driving
    the speaker into what it cannot play. So the roll-off at each end is
    found, as a run below ROLLOFF_DB reaching the end of the range, and
    the fit starts a third of an octave inside it. A dip in the middle
    does not count: it does not reach the end.
    """
    low, high = FIT_LOW, FIT_HIGH
    below = db < ROLLOFF_DB
    i = 0
    while i < len(grid) and below[i]:
        i += 1
    if i:
        low = max(low, float(grid[min(i, len(grid) - 1)]) * 2 ** (1 / 3))
    j = len(grid) - 1
    while j >= 0 and below[j]:
        j -= 1
    if j < len(grid) - 1:
        high = min(high, float(grid[max(j, 0)]) / 2 ** (1 / 3))
    return low, high


def fit(grid, db, heard_from=F_LOW):
    """Greedy peaking filters that bring db towards 0 inside fit_band,
    and never below heard_from, where the measurement is the room.

    Each round takes the largest remaining deviation, sizes the filter's Q
    from the width of that feature at half its height, and subtracts the
    filter's real response - so the next round sees what is actually left.
    """
    low, high = fit_band(grid, db)
    low = max(low, heard_from * 2 ** (1 / 3))
    band = (grid >= low) & (grid <= high)
    left = db.copy()
    filters = []
    for _ in range(MAX_FILTERS):
        i = int(np.argmax(np.where(band, np.abs(left), 0)))
        dev = left[i]
        if abs(dev) < STOP_DB:
            break
        # the feature's width at half its height, in octaves, read off the
        # grid on each side of the peak
        inside = (np.sign(left) == np.sign(dev)) & (np.abs(left) > abs(dev) / 2)
        lo, hi = i, i
        while lo > 0 and inside[lo - 1]:
            lo -= 1
        while hi < len(grid) - 1 and inside[hi + 1]:
            hi += 1
        octaves = max(np.log2(grid[hi] / grid[lo]), 1 / 6)
        # bandwidth in octaves to Q, for the half-gain bandwidth of a peaking EQ
        q = float(np.clip(np.sqrt(2**octaves) / (2**octaves - 1), Q_MIN, Q_MAX))
        gain = float(np.clip(-dev, -MAX_CUT_DB, MAX_BOOST_DB))
        fc = float(grid[i])
        filters.append((fc, gain, q))
        left = left + peaking_db(grid, fc, gain, q)
        if gain != -dev:
            # held at the limit, so what is left there is what the limit
            # allows: set it aside rather than stack another filter on it
            band = band & (np.abs(np.log2(grid / fc)) > max(octaves, 1 / 3) / 2)
    return filters, left, (low, high)


def preamp(filters):
    """Headroom for the boosts, so the filtered signal cannot clip."""
    return -max([0.0] + [g for _, g, _ in filters])


# What a PipeWire device's node.name is made of. The sink name is written
# into the drop-in as a string, so anything else - a quote above all - is
# refused rather than escaped.
SINK_NAME = re.compile(r"[A-Za-z0-9._:-]+")


def dropin(sink, label, positions, fitted, report):
    """The filter-chain module for one speaker, as a conf.d fragment.

    param_eq with one inline filter list per channel. The preamp is a
    high shelf at 0 Hz - a plain gain - which is exactly what param_eq
    makes of an AutoEQ file's "Preamp:" line (load_eq_bands), and it is
    shared by every channel so the balance between them is kept.

    A smart filter targeting the sink by name: WirePlumber routes
    everything bound for that speaker through it, never makes it the
    default, and ignores it while the speaker is absent. Each speaker gets
    its own file, so a laptop and a USB speaker each keep theirs.
    """
    name = "ashlaros_speakers." + sink.replace(":", "_")
    label = label.replace("\\", "").replace('"', "")
    gain = min(preamp(f) for f in fitted)
    bands = []
    for n, filters in enumerate(fitted, 1):
        items = [f"{{ type = bq_highshelf freq = 0 gain = {gain:.1f} q = 1.0 }}"]
        items += [f"{{ type = bq_peaking freq = {fc:.0f} gain = {g:.1f} q = {q:.2f} }}"
                  for fc, g, q in filters]
        bands.append(f"filters{n} = [\n" + "".join(f"                  {i}\n" for i in items)
                     + "                ]")
    ports = len(positions)
    return f"""# Written by ashlaros-speakers: the speaker calibration for
#   {label}
# {report}
#
# Remove it from Settings -> Speakers, or delete this file and run
#   systemctl --user restart ashlaros-speakers
context.modules = [
  {{ name = libpipewire-module-filter-chain
    args = {{
      node.description = "{label} (calibrated)"
      media.name = "{label} (calibrated)"
      filter.graph = {{
        nodes = [
          {{ type = builtin name = eq label = param_eq
            config = {{
                {chr(10).join("                " + b if i else b for i, b in enumerate(bands))}
            }}
          }}
        ]
        inputs = [ {" ".join(f'"eq:In {n}"' for n in range(1, ports + 1))} ]
        outputs = [ {" ".join(f'"eq:Out {n}"' for n in range(1, ports + 1))} ]
      }}
      audio.channels = {ports}
      audio.position = [ {" ".join(positions)} ]
      capture.props = {{
        node.name = "{name}"
        media.class = Audio/Sink
        filter.smart = true
        filter.smart.name = "{name}"
        filter.smart.target = {{ node.name = "{sink}" }}
      }}
      playback.props = {{
        node.name = "{name}.output"
        # the speaker suspends when nothing plays through the filter
        node.passive = true
        # to this speaker or nowhere: never onto headphones or HDMI
        node.dont-fallback = true
        node.linger = true
        media.role = "DSP"
      }}
    }}
  }}
]
"""


def selftest():
    """Synthetic speakers: known faults in, the fit must find and flatten them."""
    rng = np.random.default_rng(92)
    played = sweep().astype(np.float64)
    worst = 0.0
    for trial in range(8):
        faults = [
            (float(rng.uniform(120, 8000)), float(rng.choice([-1, 1]) * rng.uniform(3, 9)),
             float(rng.uniform(1.0, 3.0)))
            for _ in range(int(rng.integers(1, 4)))
        ]
        # the fault filters applied in the time domain, as a speaker would
        spectrum = np.fft.rfft(played, 2 * len(played))
        f = np.fft.rfftfreq(2 * len(played), 1 / RATE)
        gain = sum(peaking_db(f, *fault) for fault in faults)
        heard = np.fft.irfft(spectrum * 10 ** (gain / 20), 2 * len(played))
        lag = int(rng.integers(500, 5000))
        heard = np.concatenate([np.zeros(lag), heard])[: len(played) + lag]
        heard += rng.normal(0, 1e-4, len(heard))
        grid, db = response(played, [heard])
        band = (grid >= FIT_LOW) & (grid <= FIT_HIGH)
        before = float(np.std(db[band]))
        filters, left, _ = fit(grid, db)
        after = float(np.std(left[band]))
        assert delay(played, heard) == lag, (trial, "delay", delay(played, heard), lag)
        assert after < 0.5 * before or after < 0.5, (trial, before, after, faults, filters)
        worst = max(worst, after / before)
        print(f"trial {trial}: {len(faults)} fault(s), deviation {before:.2f} dB -> "
              f"{after:.2f} dB with {len(filters)} filter(s)")
    print(f"worst remaining ratio {worst:.2f}")


def sweep_file(path, channels, index):
    """The sweep in one channel of an interleaved file, silence elsewhere."""
    one = sweep()
    frames = np.zeros((len(one), channels), dtype=np.float32)
    frames[:, index] = one
    frames.tofile(path)


def check(position, played, recorded):
    """(reason, heard_from): why a capture cannot be fitted, or None, and
    the lowest frequency at which the sweep stood clear of the room.

    The capture has had its first SETTLE_SECONDS zeroed. The noise is the
    300 ms of lead silence just before the sweep, not all of it: the
    microphone's opening transient decays for a quarter of a second after
    the click (-34 dBFS at 0.1-0.25 s on the Z13), and counted as room noise
    it hid a sweep 25 dB clear of the room. The signal is the span the
    sweep occupies, both located by the delay.

    Clear of the room overall is not clear everywhere. An exponential
    sweep spends a quarter of its time below 150 Hz, where a laptop
    speaker barely plays and where room noise lives: on the Z13 the
    50-250 Hz part came in at 1 dB under a fan's hum while the sweep as a
    whole was 20 dB over it. Deconvolved, that hum reads as a flat bass
    response, the roll-off disappears, and the fit starts boosting at
    100 Hz. So the sweep is also tested in pieces, a third of an octave
    at a time from the bottom, and heard_from is where it first clears
    MIN_SNR_DB - the fit never starts below it.
    """
    if len(recorded) < len(played):
        return f"{position}: the capture is shorter than the sweep; nothing was recorded", 0.0
    peak = 20 * np.log10(float(np.max(np.abs(recorded))) + 1e-12)
    if peak > -0.1:
        return f"{position}: the microphone clipped; measure with the speaker quieter", 0.0
    lag = delay(played, recorded)
    start = lag + int(LEAD_SECONDS * RATE)
    quiet = max(int(SETTLE_SECONDS * RATE), start - int(0.35 * RATE))
    noise = recorded[quiet : start - int(0.05 * RATE)]
    signal = recorded[start : start + int(SWEEP_SECONDS * RATE)]
    rms = lambda x: np.sqrt(np.mean(x**2)) + 1e-12  # noqa: E731
    if len(noise) < RATE // 20:
        return f"{position}: the capture has no silence before the sweep", 0.0
    snr = 20 * np.log10(rms(signal) / rms(noise))
    if snr < MIN_SNR_DB:
        return (f"{position}: the sweep was only {snr:.0f} dB above the room - "
                "is the speaker muted, or the room loud?"), 0.0
    # where the sweep is at frequency f: t = T ln(f / F_LOW) / ln(F_HIGH / F_LOW)
    span = np.log(F_HIGH / F_LOW)
    heard_from = F_HIGH
    f = F_LOW
    while f < F_HIGH:
        a = start + int(SWEEP_SECONDS * np.log(f / F_LOW) / span * RATE)
        b = start + int(SWEEP_SECONDS * np.log(f * 2 ** (1 / 3) / F_LOW) / span * RATE)
        if 20 * np.log10(rms(recorded[a:b]) / rms(noise)) >= MIN_SNR_DB:
            heard_from = f
            break
        f *= 2 ** (1 / 3)
    return None, heard_from


def fit_captures(sink, label, channels):
    """channels: (position, [capture paths]) in the sink's channel order."""
    if not SINK_NAME.fullmatch(sink):
        sys.exit(f"not a PipeWire node name: {sink!r}")
    played = sweep().astype(np.float64)
    fitted, lines = [], []
    for position, paths in channels:
        # A sweep the room talked over is dropped, not fitted: on the Z13 a
        # noise burst took one of six to 3 dB above the room while the
        # other five were 25 dB clear. Only a channel with none left fails.
        recordings, refused, heard = [], [], []
        for path in paths:
            recorded = np.fromfile(path, dtype=np.float32).astype(np.float64)
            recorded[: int(SETTLE_SECONDS * RATE)] = 0
            reason, heard_from = check(position, played, recorded)
            if reason:
                refused.append(reason)
            else:
                recordings.append(recorded)
                heard.append(heard_from)
        if not recordings:
            # every sweep's own reason: they fail for different ones - a
            # knock clips one, a fan buries the next - and the first alone
            # sends the user after the wrong fix
            sys.exit("\n".join(f"{r} (sweep {n})" for n, r in enumerate(refused, 1)))
        peak = 20 * np.log10(max(float(np.max(np.abs(r))) for r in recordings) + 1e-12)
        # The median sweep's floor, not the worst: one sweep a noise burst
        # lifted to 635 Hz should not take the bass from the other two
        # (Z13, beside a fan: 504, 252 and 635 Hz for three identical
        # sweeps). Fitted from all of them, a noisy one is outvoted there.
        grid, db = response(played, recordings)
        filters, left, (low, high) = fit(grid, db, float(np.median(heard)))
        band = (grid >= low) & (grid <= high)
        fitted.append(filters)
        lines.append(f"{position}: {np.std(db[band]):.1f} dB -> {np.std(left[band]):.1f} dB "
                     f"expected from {low:.0f} Hz to {high / 1000:.1f} kHz with "
                     f"{len(filters)} filter(s), microphone peak {peak:.0f} dBFS"
                     + (f", {len(refused)} of {len(paths)} sweeps dropped as noisy"
                        if refused else ""))
    report = "; ".join(lines)
    positions = [position for position, _ in channels]
    sys.stdout.write(dropin(sink, label, positions, fitted, "deviation " + report))
    for line in lines:
        print(line, file=sys.stderr)


def main(argv):
    if argv[1:2] == ["sweep"] and len(argv) == 5:
        sweep_file(argv[2], int(argv[3]), int(argv[4]))
    elif argv[1:2] == ["fit"] and len(argv) >= 5 and all("=" in a for a in argv[4:]):
        channels = [(a.split("=", 1)[0], a.split("=", 1)[1].split(",")) for a in argv[4:]]
        fit_captures(argv[2], argv[3], channels)
    elif argv[1:2] == ["selftest"]:
        selftest()
    else:
        sys.exit(__doc__.split("\n\n")[2])


if __name__ == "__main__":
    main(sys.argv)
