"""Render MIDI files to WAV with FluidSynth and write a JSON manifest.

Requirements:
    py -m pip install mido

FluidSynth must be installed and its command-line executable available on PATH.
The original MIDI files are not modified; a temporary copy is extended to leave
room for drum sample tails before rendering.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import mido

DEFAULT_CONFIG = Path("wav_config.json")


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    required = ("soundfont", "midi_dir", "output_dir", "sample_rate", "gain", "tail_seconds")
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Config missing required keys: {', '.join(missing)}")
    return config


def extend_midi_tail(source: Path, destination: Path, tail_seconds: float) -> tuple[int | None, int | None]:
    """Save a temporary MIDI copy with extra silence after its final event."""
    midi = mido.MidiFile(source)
    tempo = 500_000
    for track in midi.tracks:
        for message in track:
            if message.type == "set_tempo":
                tempo = message.tempo
                break

    # Convert tail seconds to ticks using this file's tempo and resolution.
    extra_ticks = max(0, round(tail_seconds * mido.second2tick(
        1, midi.ticks_per_beat, tempo
    )))
    note_numbers = [
        msg.note for track in midi.tracks for msg in track
        if msg.type == "note_on" and msg.velocity > 0
    ]
    for track in midi.tracks:
        if track and track[-1].type == "end_of_track":
            track[-1].time += extra_ticks
    midi.save(destination)
    return (note_numbers[0] if note_numbers else None, round(mido.tempo2bpm(tempo)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Render MIDI files to WAV and create a JSON manifest.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="JSON config file (default: wav_config.json)")
    parser.add_argument("--midi-dir", help="Override MIDI input directory")
    parser.add_argument("--out", help="Override WAV output directory")
    parser.add_argument("--soundfont", help="Override SoundFont path")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_file():
        raise SystemExit(f"Config not found: {config_path.resolve()}")

    config = load_config(config_path)
    midi_dir = Path(args.midi_dir or config["midi_dir"])
    output_dir = Path(args.out or config["output_dir"])
    soundfont = Path(args.soundfont or config["soundfont"])
    sample_rate = int(config["sample_rate"])
    gain = float(config["gain"])
    tail_seconds = float(config["tail_seconds"])

    fluidsynth = shutil.which(config.get("fluidsynth_command", "fluidsynth"))
    if not fluidsynth:
        raise SystemExit(
            "FluidSynth command not found. Add fluidsynth.exe to PATH or set "
            "'fluidsynth_command' in wav_config.json to its full path."
        )
    if not soundfont.is_file():
        raise SystemExit(f"SoundFont not found: {soundfont}")
    if not midi_dir.is_dir():
        raise SystemExit(f"MIDI input folder not found: {midi_dir}")

    midi_files = sorted(midi_dir.glob("*.mid"))
    if not midi_files:
        raise SystemExit(f"No .mid files found in: {midi_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries = []
    failures = []

    with tempfile.TemporaryDirectory(prefix="joycon_midi_") as temp_dir:
        temp_dir_path = Path(temp_dir)
        for midi_path in midi_files:
            wav_path = output_dir / f"{midi_path.stem}.wav"
            temp_midi = temp_dir_path / midi_path.name
            note, tempo_bpm = extend_midi_tail(midi_path, temp_midi, tail_seconds)

            command = [
                fluidsynth, "-ni", "-r", str(sample_rate), "-g", str(gain),
                "-F", str(wav_path), str(soundfont), str(temp_midi),
            ]
            print(f"Rendering: {midi_path.name} -> {wav_path.name}")
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0 or not wav_path.is_file() or wav_path.stat().st_size == 0:
                detail = (result.stderr or result.stdout or "No error details returned").strip()
                failures.append({"midi": midi_path.name, "error": detail})
                print(f"  ERROR: {detail}")
                continue

            manifest_entries.append({
                "note_number": note,
                "midi_file": str(midi_path.as_posix()),
                "wav_file": str(wav_path.as_posix()),
                "tempo_bpm": tempo_bpm,
                "sample_rate_hz": sample_rate,
                "channels": 2,
                "format": "WAV",
                "gain": gain,
                "tail_seconds": tail_seconds,
                "wav_size_bytes": wav_path.stat().st_size,
            })

    manifest = {
        "schema_version": 1,
        "generator": "convert_midi_to_wav.py",
        "soundfont": str(soundfont),
        "sample_rate_hz": sample_rate,
        "gain": gain,
        "tail_seconds": tail_seconds,
        "midi_input_dir": str(midi_dir.as_posix()),
        "wav_output_dir": str(output_dir.as_posix()),
        "file_count": len(manifest_entries),
        "files": manifest_entries,
        "failures": failures,
    }
    manifest_path = output_dir / "wav_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\nDone: {len(manifest_entries)}/{len(midi_files)} WAV files rendered.")
    print(f"Manifest: {manifest_path.resolve()}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
