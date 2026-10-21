"""Generate one-hit General MIDI drum files for Joy-Con experiments.

Each output MIDI contains exactly one percussion note on channel 10 (MIDI channel 9).
Tempo is fixed at 120 BPM. Requires: pip install mido
"""
from pathlib import Path
import argparse
import mido

TEMPO_BPM = 120
TICKS_PER_BEAT = 480
DRUM_CHANNEL = 9  # MIDI channel 10 (zero-based)
NOTE_LENGTH_BEATS = 0.25

# General MIDI percussion map: note number -> descriptive filename
DRUM_NOTES = {
    35: "acoustic_bass_drum",
    36: "bass_drum_kick",
    37: "side_stick",
    38: "acoustic_snare",
    39: "hand_clap",
    40: "electric_snare",
    41: "low_floor_tom",
    42: "closed_hi_hat",
    43: "high_floor_tom",
    44: "pedal_hi_hat",
    45: "low_tom",
    46: "open_hi_hat",
    47: "low_mid_tom",
    48: "high_mid_tom",
    49: "crash_cymbal_1",
    50: "high_tom",
    51: "ride_cymbal_1",
    52: "china_cymbal",
    53: "ride_bell",
    54: "tambourine",
    55: "splash_cymbal",
    56: "cowbell",
    57: "crash_cymbal_2",
    58: "vibraslap",
    59: "ride_cymbal_2",
    60: "high_bongo",
    61: "low_bongo",
    62: "mute_high_conga",
    63: "open_high_conga",
    64: "low_conga",
    65: "high_timbale",
    66: "low_timbale",
    67: "high_agogo",
    68: "low_agogo",
    69: "cabasa",
    70: "maracas",
    71: "short_whistle",
    72: "long_whistle",
    73: "short_guiro",
    74: "long_guiro",
    75: "claves",
    76: "high_wood_block",
    77: "low_wood_block",
    78: "mute_cuica",
    79: "open_cuica",
    80: "mute_triangle",
    81: "open_triangle",
}


def make_one_hit_midi(note: int, velocity: int = 100) -> mido.MidiFile:
    """Build a MIDI containing one percussion note."""
    midi = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    midi.tracks.append(track)

    tempo = mido.bpm2tempo(TEMPO_BPM)
    track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    track.append(mido.Message(
        "note_on", channel=DRUM_CHANNEL, note=note,
        velocity=velocity, time=0
    ))
    track.append(mido.Message(
        "note_off", channel=DRUM_CHANNEL, note=note,
        velocity=0, time=int(TICKS_PER_BEAT * NOTE_LENGTH_BEATS)
    ))
    track.append(mido.MetaMessage("end_of_track", time=0))
    return midi


def generate_all(output_dir: Path, velocity: int = 100) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    for note, name in DRUM_NOTES.items():
        path = output_dir / f"{note:02d}_{name}.mid"
        make_one_hit_midi(note, velocity).save(path)
        print(f"Created: {path}")
    print(f"\nDone: {len(DRUM_NOTES)} MIDI files saved to {output_dir.resolve()}")
    print(f"Tempo: {TEMPO_BPM} BPM | One note per file | Velocity: {velocity}")
    return len(DRUM_NOTES)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate one-hit drum MIDI files.")
    parser.add_argument("--out", default="midi_notes", help="Output folder (default: midi_notes)")
    parser.add_argument("--velocity", type=int, default=100, help="MIDI velocity, 1-127 (default: 100)")
    args = parser.parse_args()

    if not 1 <= args.velocity <= 127:
        parser.error("--velocity must be between 1 and 127")

    generate_all(Path(args.out), args.velocity)


if __name__ == "__main__":
    main()
