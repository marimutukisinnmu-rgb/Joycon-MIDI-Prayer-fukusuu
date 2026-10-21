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
