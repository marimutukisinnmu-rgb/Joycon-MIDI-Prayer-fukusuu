"""Experimental 1-4 Joy-Con MIDI rumble player.

Routing:
  J1: Low = Track A, High = Track B
  J2: Low + High = Track C
  J3: Low + High = Track D
  J4: Low + High = Track E

Input:
  -files ""             opens a MIDI file picker (Windows desktop)
  -files song.mid       one MIDI with up to five drum tracks (channel 10), mapped A-E
  -files A.mid B.mid C.mid D.mid E.mid
                        five MIDI files, one per track A-E

Strength:
  --strength 25         scale note amplitudes to 25% of their original value
  --strength 100        use the full calculated amplitude
  --strength 0          silence all note amplitudes
  --log                 print each Joy-Con rumble payload in hex and binary

Mixed MIDI attenuation:
  Each Joy-Con is automatically attenuated by 50% when assigned two channels,
  or when either assigned channel contains 4+ note-ons within one beat.
  J1 retains its additional 50% loudness precaution; --strength remains global.
  Valid range is 0-100%. Perceived vibration and sound do not scale linearly.

With fewer than four Joy-Cons, the program uses the connected/selected devices
in order, so one Joy-Con tests A/B, two test A/B and C, and so on.

This is an experimental encoding based on the project's current rumble tests.
It does not guarantee accurate or perceptually independent frequency reproduction.
Requires: pip install hidapi mido
"""
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path
from typing import Any

import hid
import mido

VID = 0x057E
JOYCON_PIDS = {0x2006, 0x2007}  # Left and Right Joy-Con
NEUTRAL = bytes([0x00, 0x01, 0x40, 0x40])
TRACK_NAMES = ("A", "B", "C", "D", "E")
MIN_FREQ = 40.0
MAX_FREQ = 1252.0
MIN_STRENGTH_PERCENT = 0
MAX_STRENGTH_PERCENT = 100
DEFAULT_STRENGTH_PERCENT = 25  # Conservative starting scale


def encode_amplitude(amp: float) -> int:
    amp = max(0.0, min(1.0, float(amp)))
    if amp <= 0.0:
        return 0
    if amp > 0.23:
        return round(math.log2(amp * 8.7) * 32.0)
    if amp > 0.12:
        return round(math.log2(amp * 17.0) * 16.0)
    return 0


def make_rumble(low_freq: float, low_amp: float,
                high_freq: float, high_amp: float) -> bytes:
    """Build one motor's 4-byte rumble payload using the experimental encoder."""
    low_freq = max(MIN_FREQ, min(626.286133, float(low_freq)))
    high_freq = max(81.75177, min(MAX_FREQ, float(high_freq)))
    low_amp = max(0.0, min(1.0, float(low_amp)))
    high_amp = max(0.0, min(1.0, float(high_amp)))

    high_encoded = round(math.log2(high_freq / 10.0) * 32.0)
    low_encoded = round(math.log2(low_freq / 10.0) * 32.0)
    hf = (high_encoded - 0x60) * 4
    lf = low_encoded - 0x40
    high_enc_amp = encode_amplitude(high_amp)
    low_enc_amp = encode_amplitude(low_amp)
    hf_amp = high_enc_amp * 2
    lf_amp = low_enc_amp // 2 + 0x40 if low_amp > 0 else 0

    return bytes([
        hf & 0xFF,
        (hf_amp + ((hf >> 8) & 0xFF)) & 0xFF,
        (lf + ((lf_amp >> 8) & 0xFF)) & 0xFF,
        lf_amp & 0xFF,
    ])


class JoyConDevice:
    def __init__(self, path: Any, label: str):
        self.path = path
        self.label = label
        self.dev = hid.device()
        self.packet = 0
        self.connected = False

    def _next_packet(self) -> int:
        value = self.packet
        self.packet = (self.packet + 1) & 0x0F
        return value

    def connect(self) -> None:
        self.dev.open_path(self.path)
        self.connected = True
        self.dev.set_nonblocking(False)
        self.enable_rumble()
        print(f"Connected: {self.label}")

    def enable_rumble(self) -> None:
        buf = bytearray(64)
        buf[0] = 0x01
        buf[1] = self._next_packet()
        buf[2:10] = NEUTRAL + NEUTRAL
        buf[10] = 0x48
        buf[11] = 0x01
        self.dev.write(buf)
        try:
            self.dev.read(64)
        except Exception:
            pass

    def send(self, left: bytes, right: bytes) -> None:
        if not self.connected:
            return
        buf = bytearray(64)
        buf[0] = 0x10
        buf[1] = self._next_packet()
        buf[2:6] = left
        buf[6:10] = right
        self.dev.write(buf)

    def stop(self) -> None:
        if self.connected:
            self.send(NEUTRAL, NEUTRAL)

    def close(self) -> None:
        if self.connected:
            try:
                self.stop()
            finally:
                self.dev.close()
                self.connected = False


def find_joycons() -> list[dict[str, Any]]:
    found = []
    for item in hid.enumerate(VID, 0):
        if item.get("product_id") in JOYCON_PIDS and item.get("path"):
            found.append(item)
    return found


def choose_joycons() -> list[JoyConDevice]:
    found = find_joycons()
    if not found:
        raise RuntimeError(
            "No Joy-Con HID interfaces found. Connect at least one Joy-Con "
            "and close software that may be using it."
        )
    print("Detected Joy-Con HID interfaces:")
    for i, item in enumerate(found):
        side = "Left" if item["product_id"] == 0x2006 else "Right"
        print(f"  [{i}] {side} Joy-Con | product={item.get('product_string')} "
              f"| serial={item.get('serial_number') or '(none)'}")
    max_count = min(4, len(found))
    print(f"Select 1-{max_count} interface(s); enter indexes separated by commas.")
    prompt = f"Choose index(es) (example: 0,2; max {max_count}): "
    raw = input(prompt)
    try:
        indexes = [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError as exc:
        raise RuntimeError("Indexes must be numbers separated by commas.") from exc
    if not indexes or len(indexes) > max_count or len(set(indexes)) != len(indexes):
        raise RuntimeError(f"Enter 1-{max_count} different indexes.")
    if any(i < 0 or i >= len(found) for i in indexes):
        raise RuntimeError("One or more indexes are out of range.")
    return [
        JoyConDevice(found[i]["path"], f"J{j + 1} (index {i})")
        for j, i in enumerate(indexes)
    ]


def select_files(file_args: list[str]) -> list[Path]:
    cleaned = [x for x in file_args if x.strip()]
    if not cleaned:
        # -files "" intentionally opens a picker.
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            selected = filedialog.askopenfilenames(
                title="Select one full MIDI, or five MIDI files A-E",
                filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*.*")]
            )
            root.destroy()
            cleaned = list(selected)
        except Exception as exc:
            raise RuntimeError(
                'No MIDI path provided. Use -files "song.mid" or a GUI file picker.'
            ) from exc
    paths = [Path(x).expanduser() for x in cleaned]
    if not paths:
        raise RuntimeError("No MIDI files selected.")
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError("MIDI file(s) not found: " + ", ".join(missing))
    if len(paths) not in (1, 5):
        raise RuntimeError("Provide either one full MIDI or exactly five files A-E.")
    return paths


def load_track_events(paths: list[Path]) -> list[list[tuple[float, str, int, int]]]:
    """Return A-E event lists: (seconds, event type, note, velocity)."""
    events: list[list[tuple[float, str, int, int]]] = [[] for _ in TRACK_NAMES]
    if len(paths) == 5:
        for track_idx, path in enumerate(paths):
            midi = mido.MidiFile(path)
            elapsed = 0.0
            for msg in midi:
                elapsed += msg.time  # Mido's merged iterator yields seconds.
                if msg.type in ("note_on", "note_off"):
                    kind = "on" if msg.type == "note_on" and msg.velocity > 0 else "off"
                    events[track_idx].append((elapsed, kind, msg.note, msg.velocity))
        return events

    midi = mido.MidiFile(paths[0])
    drum_tracks = []
    for track in midi.tracks:
        if any(getattr(msg, "channel", None) == 9 and msg.type in ("note_on", "note_off")
               for msg in track):
            drum_tracks.append(track)
    if not drum_tracks:
        raise RuntimeError("No channel-10 percussion tracks found in the selected MIDI.")
    if len(drum_tracks) > 5:
        print(f"Found {len(drum_tracks)} channel-10 tracks; using the first five as A-E.")
    for track_idx, track in enumerate(drum_tracks[:5]):
        elapsed = 0.0
        tempo = 500000
        for msg in track:
            if msg.type == "set_tempo":
                tempo = msg.tempo
            elapsed += mido.tick2second(msg.time, midi.ticks_per_beat, tempo)
            if getattr(msg, "channel", None) == 9 and msg.type in ("note_on", "note_off"):
                kind = "on" if msg.type == "note_on" and msg.velocity > 0 else "off"
                events[track_idx].append((elapsed, kind, msg.note, msg.velocity))
    return events



def load_mixed_events(path: Path) -> tuple[list[list[tuple[float, str, int, int]]], list[tuple[float, int, int]], list[bool]]:
    """Load MIDI channels 1-8 plus channel-10 percussion using Mido's merged timeline.

    Returns eight note-event lists and drum hits as (seconds, note, velocity).
    Mido's merged iterator applies tempo changes across the whole MIDI file.
    """
    midi = mido.MidiFile(path)
    channels: list[list[tuple[float, str, int, int]]] = [[] for _ in range(8)]
    drums: list[tuple[float, int, int]] = []
    tempo_changes: list[tuple[float, int]] = [(0.0, 500000)]
    elapsed = 0.0
    current_tempo = 500000
    note_on_times: list[list[float]] = [[] for _ in range(8)]
    for msg in midi:
        elapsed += msg.time
        if msg.type == "set_tempo":
            current_tempo = msg.tempo
            tempo_changes.append((elapsed, current_tempo))
            continue
        if msg.type not in ("note_on", "note_off"):
            continue
        channel = getattr(msg, "channel", None)
        is_on = msg.type == "note_on" and msg.velocity > 0
        if channel in range(8):
            kind = "on" if is_on else "off"
            channels[channel].append((elapsed, kind, msg.note, msg.velocity))
            if is_on:
                note_on_times[channel].append(elapsed)
        elif channel == 9 and is_on:
            drums.append((elapsed, msg.note, msg.velocity))

    # A fast roll means four or more note-on events in a window no longer than
    # one beat. Use the tempo active at the beginning of each candidate window.
    def beat_seconds_at(moment: float) -> float:
        tempo = 500000
        for tempo_time, tempo_value in tempo_changes:
            if tempo_time > moment:
                break
            tempo = tempo_value
        return tempo / 1_000_000.0

    fast_channels = [False] * 8
    for ch, onset_times in enumerate(note_on_times):
        for i in range(len(onset_times) - 3):
            window_start = onset_times[i]
            if onset_times[i + 3] - window_start <= beat_seconds_at(window_start):
                fast_channels[ch] = True
                break
    return channels, drums, fast_channels


def strongest_active_note(active: dict[int, tuple[float, float]]) -> tuple[float, float] | None:
    """A single rumble component can represent only one pitch: choose the loudest active note."""
    if not active:
        return None
    return max(active.values(), key=lambda item: item[1])


def note_frequency(note: int) -> float:
    # Experimental mapping: MIDI note number to equal-tempered frequency.
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def velocity_amplitude(velocity: int, strength_percent: int) -> float:
    """Convert MIDI velocity to amplitude and scale it by the selected percentage."""
    raw_amp = 0.15 + (0.65 - 0.15) * (velocity / 127.0)
    scale = max(MIN_STRENGTH_PERCENT, min(MAX_STRENGTH_PERCENT, strength_percent)) / 100.0
    return raw_amp * scale


def format_payload(payload: bytes) -> str:
    """Format a payload as both hexadecimal bytes and 8-bit binary bytes."""
    hex_bytes = " ".join(f"{byte:02X}" for byte in payload)
    binary_bytes = " ".join(f"{byte:08b}" for byte in payload)
    return f"HEX=[{hex_bytes}] BIN=[{binary_bytes}]"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Play MIDI channels 1-8 and channel-10 drums through 1-4 Joy-Cons."
    )
    parser.add_argument("-files", "--files", nargs="*", default=[],
                        help='one mixed MIDI, five legacy MIDI files A-E, or "" to open a file picker')
    parser.add_argument("--mode", choices=("mixed", "piano"), default="mixed",
                        help="mixed: channels 1-8 plus channel-10 drums; piano: melodic notes only")
    parser.add_argument("--skip-first-bar", action="store_true",
                        help="skip one measure before playback")
    parser.add_argument("--bpm", type=float, default=120.0,
                        help="tempo used to calculate the skipped 4/4 bar (default: 120)")
    parser.add_argument("--strength", type=int, default=DEFAULT_STRENGTH_PERCENT,
                        choices=range(MIN_STRENGTH_PERCENT, MAX_STRENGTH_PERCENT + 1),
                        metavar="0-100",
                        help="scale calculated rumble amplitude by this percentage (default: 25)")
    parser.add_argument("--log", action="store_true",
                        help="log each Joy-Con rumble payload as hexadecimal and binary")
    args = parser.parse_args()
    if args.bpm <= 0:
        parser.error("--bpm must be greater than zero")

    paths = select_files(args.files)
    mixed_mode = len(paths) == 1
    piano_mode = mixed_mode and args.mode == "piano"
    if mixed_mode:
        channel_events, drum_hits, fast_channels = load_mixed_events(paths[0])
        if piano_mode:
            drum_hits = []
        events = None
    else:
        events = load_track_events(paths)
        channel_events, drum_hits, fast_channels = None, [], [False] * 8
        for track_events in events:
            track_events.sort(key=lambda x: x[0])

    connected: list[JoyConDevice] = []
    try:
        devices = choose_joycons()
        for device in devices:
            device.connect()
            connected.append(device)

        if args.skip_first_bar:
            bar_seconds = 4.0 * 60.0 / args.bpm
            if mixed_mode:
                channel_events = [[(t - bar_seconds, kind, note, velocity)
                                   for t, kind, note, velocity in channel
                                   if t >= bar_seconds] for channel in channel_events]
                drum_hits = [(t - bar_seconds, note, velocity)
                             for t, note, velocity in drum_hits if t >= bar_seconds]
            else:
                events = [[(t - bar_seconds, kind, note, velocity)
                           for t, kind, note, velocity in track
                           if t >= bar_seconds] for track in events]
            print(f"Skipping the first 4/4 bar ({bar_seconds:.2f} s at {args.bpm:g} BPM).")

        print(f"Connected playback devices: {len(devices)} Joy-Con(s).")
        if mixed_mode:
            if piano_mode:
                print("Piano mode: MIDI channels 1-8 mapped to Joy-Con motor components; note-off controls note length.")
            else:
                print("Mixed MIDI routing: J1 Low=CH1 / High=CH2; J2 CH3 / CH4; J3 CH5 / CH6; J4 CH7 / CH8.")
                print("Channel 10 drums are layered as short hits across connected Joy-Cons.")
            print("Auto attenuation: halve a Joy-Con when it has two assigned channels or either assigned channel has 4+ note-ons within one beat.")
            print("Polyphony note: each motor component can express one pitch at a time; the strongest active note is selected.")
        else:
            print("Legacy five-file routing: J1=A/B; J2=C; J3=D; J4=E.")
        print(f"Global rumble amplitude scale: {args.strength}% (range 0-100; default 25%).")
        if not piano_mode:
            print("J1 amplitude is additionally halved as a loudness precaution.")
        print("Experimental rumble encoding; perceived vibration/sound is nonlinear. Press Ctrl+C to stop.")
        if args.log:
            print("Payload logging enabled: each Jx line shows the 4-byte motor payload in HEX and BIN.")

        start = time.perf_counter()
        if mixed_mode:
            positions = [0] * 8
            active_channels: list[dict[int, tuple[float, float]]] = [dict() for _ in range(8)]
            drum_pos = 0
            drum_until = 0.0
            drum_note: tuple[float, float] | None = None
            while True:
                now = time.perf_counter() - start
                all_notes_done = all(positions[i] >= len(channel_events[i]) for i in range(8))
                if all_notes_done and drum_pos >= len(drum_hits) and not any(active_channels) and now >= drum_until:
                    break
                changed = False
                for ch, channel in enumerate(channel_events):
                    while positions[ch] < len(channel) and channel[positions[ch]][0] <= now:
                        _, kind, note, velocity = channel[positions[ch]]
                        if kind == "on":
                            active_channels[ch][note] = (
                                note_frequency(note), velocity_amplitude(velocity, args.strength)
                            )
                        else:
                            active_channels[ch].pop(note, None)
                        positions[ch] += 1
                        changed = True
                while drum_pos < len(drum_hits) and drum_hits[drum_pos][0] <= now:
                    _, drum_pitch, drum_velocity = drum_hits[drum_pos]
                    drum_note = (
                        note_frequency(max(24, min(96, drum_pitch))),
                        velocity_amplitude(drum_velocity, args.strength)
                    )
                    drum_until = now + 0.085
                    drum_pos += 1
                    changed = True
                if drum_note is not None and now >= drum_until:
                    drum_note = None
                    changed = True
                if changed:
                    for jc_index, device in enumerate(devices):
                        low_ch = jc_index * 2
                        high_ch = low_ch + 1
                        low_note = strongest_active_note(active_channels[low_ch])
                        high_note = strongest_active_note(active_channels[high_ch])
                        if drum_note is not None:
                            # Brief percussion overlay takes priority for the hit's 85 ms.
                            low_note = drum_note
                            high_note = drum_note
                        low_freq, low_amp = low_note if low_note else (120.0, 0.0)
                        high_freq, high_amp = high_note if high_note else (200.0, 0.0)
                        # Mixed mode attenuates busy channel pairs; piano mode preserves selected strength.
                        if not piano_mode:
                            assigned_channels = (low_ch, high_ch)
                            apply_half = len(assigned_channels) >= 2 or any(fast_channels[ch] for ch in assigned_channels)
                            if apply_half:
                                low_amp *= 0.5
                                high_amp *= 0.5
                            if jc_index == 0:
                                low_amp *= 0.5
                                high_amp *= 0.5
                        payload = make_rumble(low_freq, low_amp, high_freq, high_amp)
                        device.send(payload, payload)
                        if args.log:
                            print(f"[{now:8.3f}s] J{jc_index + 1}: {format_payload(payload)}")
                time.sleep(0.001)
        else:
            positions = [0] * 5
            active: list[dict[int, tuple[float, float]]] = [dict() for _ in range(5)]
            while True:
                now = time.perf_counter() - start
                if all(positions[i] >= len(events[i]) for i in range(5)) and not any(active):
                    break
                changed = False
                for i, track_events in enumerate(events):
                    while positions[i] < len(track_events) and track_events[positions[i]][0] <= now:
                        _, kind, note, velocity = track_events[positions[i]]
                        if kind == "on":
                            active[i][note] = (note_frequency(note), velocity_amplitude(velocity, args.strength))
                        else:
                            active[i].pop(note, None)
                        positions[i] += 1
                        changed = True
                if changed:
                    for jc_index, device in enumerate(devices):
                        low_track = ("A", "C", "D", "E")[jc_index]
                        high_track = ("B", "C", "D", "E")[jc_index]
                        low_idx = TRACK_NAMES.index(low_track)
                        high_idx = TRACK_NAMES.index(high_track)
                        low_note = strongest_active_note(active[low_idx])
                        high_note = strongest_active_note(active[high_idx])
                        low_freq, low_amp = low_note if low_note else (120.0, 0.0)
                        high_freq, high_amp = high_note if high_note else (200.0, 0.0)
                        if jc_index == 0:
                            low_amp *= 0.5
                            high_amp *= 0.5
                        payload = make_rumble(low_freq, low_amp, high_freq, high_amp)
                        device.send(payload, payload)
                        if args.log:
                            print(f"[{now:8.3f}s] J{jc_index + 1}: {format_payload(payload)}")
                time.sleep(0.001)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        for device in reversed(connected):
            device.close()
    print("Playback finished.")


if __name__ == "__main__":
    main()
