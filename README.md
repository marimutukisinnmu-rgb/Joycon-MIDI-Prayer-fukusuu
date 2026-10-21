# Joycon-MIDI-Prayer-fukusuu

Generate individual General MIDI percussion hits for experiments with Joy-Con rumble.

## Features

- Fixed tempo: **120 BPM**
- One percussion note per MIDI file (not a full drum pattern)
- Writes 47 individual `.mid` files into `midi_notes/`
- Uses General MIDI percussion on channel 10
- MIDI generation only; WAV rendering and Joy-Con playback are separate steps

## Setup

Python 3.10+ is recommended.

```powershell
py -m pip install mido
```

## Generate the MIDI files

Run from the repository folder:

```powershell
py generate_mid.py
```

This creates a `midi_notes` folder containing files such as `36_bass_drum_kick.mid`, `38_acoustic_snare.mid`, and `39_hand_clap.mid`.

Choose a different MIDI velocity (1–127):

```powershell
py generate_mid.py --velocity 110
```

Choose a different output directory:

```powershell
py generate_mid.py --out my_midi_notes
```

## Use from another Python file

The generator can also be imported:

```python
from pathlib import Path
from generate_mid import DRUM_NOTES, make_one_hit_midi

# Create just the bass drum hit (MIDI note 36).
midi = make_one_hit_midi(36, velocity=110)
midi.save(Path("36_bass_drum_kick.mid"))
```

Note: a MIDI file describes a sound event; the actual sound depends on the MIDI synthesizer and its SoundFont. Joy-Con rumble playback will be implemented separately.


## Experimental 4-Joy-Con MIDI rumble playback

The experimental player `joycon_midi_rumble_4jc.py` maps five channel-10 drum tracks to four Joy-Cons:

| Controller | Low band | High band |
|---|---|---|
| J1 | Track A | Track B |
| J2 | Track C | Track C |
| J3 | Track D | Track D |
| J4 | Track E | Track E |

Track A-E means the first through fifth MIDI tracks containing channel-10 note events. With five separate MIDI files, the command-line order is A, B, C, D, E.

Install dependencies:

```powershell
py -m pip install hidapi mido
```

Select a MIDI file using the file picker (the requested `--files ""` form):

```powershell
py joycon_midi_rumble_4jc.py --files ""
```

Or provide one full MIDI file:

```powershell
py joycon_midi_rumble_4jc.py --files "E:\\music\\song.mid"
```

Or provide five separate MIDI files in A-E order:

```powershell
py joycon_midi_rumble_4jc.py --files "A.mid" "B.mid" "C.mid" "D.mid" "E.mid"
```

Connect four Joy-Cons before starting. The program lists detected HID interfaces and asks you to choose four indexes. If the MIDI's first measure should be reserved for piano, add `--skip-first-bar --bpm 120`; this filters drum events from the first 4/4 bar.

**Experimental limitation:** Low/High encoding is based on the current project experiment and has not yet been verified as protocol-accurate. One band can carry only one currently selected note; overlapping notes on the same track/band are not independently reproduced. Test with low amplitude first.
