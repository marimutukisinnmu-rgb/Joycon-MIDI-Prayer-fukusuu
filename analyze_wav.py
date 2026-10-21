#!/usr/bin/env python3
"""Analyze WAV files listed in wav_manifest.json and create vibration_patterns.json.

Run from the project root:
    python analyze_wav.py
Optional:
    python analyze_wav.py --manifest wav_notes/wav_manifest.json --output vibration_patterns.json

Only Python's standard library and NumPy are required.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import wave
from pathlib import Path

import numpy as np


def read_wav(path: Path) -> tuple[np.ndarray, int, int]:
    """Return normalized float32 samples (frames, channels), sample rate, channels."""
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)

    if sample_width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 3:
        bytes_ = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        ints = (bytes_[:, 0].astype(np.int32)
                | (bytes_[:, 1].astype(np.int32) << 8)
                | (bytes_[:, 2].astype(np.int32) << 16))
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        samples = ints.astype(np.float32) / 8388608.0
    elif sample_width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported PCM sample width: {sample_width} bytes")

    if channels < 1:
        raise ValueError("WAV has no channels")
    return samples.reshape(-1, channels), sample_rate, channels


def analyze_file(path: Path, window_ms: int, max_events: int) -> dict:
    samples, sample_rate, channels = read_wav(path)
    if samples.size == 0:
        raise ValueError("WAV contains no audio frames")

    mono = samples.mean(axis=1)
    duration = len(mono) / sample_rate
    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))

    window_frames = max(1, int(sample_rate * window_ms / 1000))
    window_stats = []
    for start in range(0, len(mono), window_frames):
        frame = mono[start:start + window_frames]
        if frame.size == 0:
            continue
        frame_rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))
        frame_peak = float(np.max(np.abs(frame)))
        # Spectral centroid is a timbre descriptor, not the Joy-Con motor frequency.
        if frame.size >= 16 and frame_peak > 1e-7:
            spectrum = np.abs(np.fft.rfft(frame * np.hanning(frame.size)))
            freqs = np.fft.rfftfreq(frame.size, d=1.0 / sample_rate)
            total = float(spectrum.sum())
            centroid = float(np.dot(freqs, spectrum) / total) if total > 1e-12 else 0.0
        else:
            centroid = 0.0
        window_stats.append({
            "time_ms": round(start * 1000 / sample_rate),
            "rms": round(frame_rms, 6),
            "peak": round(frame_peak, 6),
            "spectral_centroid_hz": round(centroid, 1),
        })

    # Ignore the long rendered silence when estimating the sound's active duration.
    active_threshold = max(0.002, peak * 0.03)
    active = [item for item in window_stats if item["rms"] >= active_threshold]
    active_duration_ms = (
        min(len(mono) * 1000 / sample_rate,
            active[-1]["time_ms"] + window_ms) if active else 0
    )

    # Map relative window loudness to a conservative suggested vibration amplitude.
    # This is a starting point for tuning, not a physical audio-to-vibration equivalence.
    max_window_rms = max((item["rms"] for item in window_stats), default=0.0)
    events = []
    for item in window_stats:
        if item["rms"] < max(0.0015, max_window_rms * 0.04):
            continue
        relative = item["rms"] / max_window_rms if max_window_rms > 0 else 0.0
        amplitude = min(0.75, max(0.08, math.sqrt(relative) * 0.65))
        events.append({
            "time_ms": item["time_ms"],
            "duration_ms": window_ms,
            "amplitude": round(amplitude, 3),
            "audio_rms": item["rms"],
            "spectral_centroid_hz": item["spectral_centroid_hz"],
        })

    # Bound JSON size for unexpectedly long samples while keeping the strongest events.
    if len(events) > max_events:
        stride = math.ceil(len(events) / max_events)
        events = events[::stride]

    return {
        "duration_seconds": round(duration, 4),
        "active_duration_ms_estimate": round(active_duration_ms),
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "peak_amplitude": round(peak, 6),
        "rms_loudness": round(rms, 6),
        "analysis_window_ms": window_ms,
        "suggested_vibration_events": events,
        "notes": [
            "amplitude is a conservative starting suggestion; tune by testing on your Joy-Con",
            "spectral_centroid_hz describes the audio and is not the Joy-Con motor frequency",
            "events are windowed suggestions; combine adjacent events when implementing playback",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="wav_notes/wav_manifest.json",
                        help="Path to wav_manifest.json (default: wav_notes/wav_manifest.json)")
    parser.add_argument("--output", default="vibration_patterns.json",
                        help="Output JSON path (default: vibration_patterns.json)")
    parser.add_argument("--window-ms", type=int, default=20,
                        help="Analysis window size in milliseconds (default: 20)")
    parser.add_argument("--max-events", type=int, default=400,
                        help="Maximum suggested events per WAV (default: 400)")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    output_path = Path(args.output).resolve()
    if args.window_ms < 5 or args.window_ms > 200:
        parser.error("--window-ms must be between 5 and 200")
    if args.max_events < 1:
        parser.error("--max-events must be at least 1")
    if not manifest_path.is_file():
        raise SystemExit(f"Manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_dir = manifest_path.parent
    project_root = manifest_dir.parent if manifest_dir.name == "wav_notes" else manifest_dir
    results = []
    failures = []

    for entry in manifest.get("files", []):
        relative_wav = Path(entry["wav_file"])
        # Manifest paths are project-root-relative, e.g. wav_notes/35_name.wav.
        wav_path = (project_root / relative_wav).resolve()
        if not wav_path.is_file():
            # Also support paths relative to the manifest directory.
            alternative = (manifest_dir / relative_wav.name).resolve()
            if alternative.is_file():
                wav_path = alternative
            else:
                failures.append({"wav_file": entry.get("wav_file"), "error": "file not found"})
                continue
        try:
            analysis = analyze_file(wav_path, args.window_ms, args.max_events)
            results.append({
                "note_number": entry.get("note_number"),
                "midi_file": entry.get("midi_file"),
                "wav_file": entry.get("wav_file"),
                **analysis,
            })
            print(f"[OK] note {entry.get('note_number')}: {wav_path.name}")
        except (OSError, ValueError, wave.Error, json.JSONDecodeError) as exc:
            failures.append({"wav_file": entry.get("wav_file"), "error": str(exc)})
            print(f"[FAIL] {entry.get('wav_file')}: {exc}")

    output = {
        "schema_version": 1,
        "generator": "analyze_wav.py",
        "source_manifest": str(Path(args.manifest).as_posix()),
        "analysis_method": {
            "window_ms": args.window_ms,
            "loudness": "RMS of mono mix",
            "peak": "maximum absolute sample value",
            "spectral_centroid": "magnitude-weighted FFT frequency centroid",
            "vibration_amplitude_mapping": "sqrt(relative window RMS), capped at 0.75",
        },
        "file_count": len(results),
        "failure_count": len(failures),
        "files": results,
        "failures": failures,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"\nDone: {len(results)} analyzed, {len(failures)} failed")
    print(f"Output: {output_path}")
    return 0 if results and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
