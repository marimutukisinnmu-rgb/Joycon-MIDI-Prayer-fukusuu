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
    count = min(4, len(found))
    if len(found) < 4:
        print(f"Only {len(found)} matching HID interface(s) found; entering partial test mode.")
        print(f"Will use {count} interface(s).")
    prompt = (
        f"Choose {count} index(es) separated by commas "
        f"(example: {','.join(str(i) for i in range(count))}): "
    )
    raw = input(prompt)
    try:
        indexes = [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError as exc:
        raise RuntimeError("Indexes must be numbers separated by commas.") from exc
    if len(indexes) != count or len(set(indexes)) != count:
        raise RuntimeError(f"Enter exactly {count} different indexes.")
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


def note_frequency(note: int) -> float:
    # Experimental mapping: MIDI note number to equal-tempered frequency.
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def velocity_amplitude(velocity: int) -> float:
    return 0.15 + (0.65 - 0.15) * (velocity / 127.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Play channel-10 MIDI drums as 1-4 Joy-Con rumble.")
    parser.add_argument("-files", "--files", nargs="*", default=[],
                        help='one MIDI path, five paths A-E, or "" to open a file picker')
    parser.add_argument("--skip-first-bar", action="store_true",
                        help="skip one measure before starting drums (default: off)")
    parser.add_argument("--bpm", type=float, default=120.0,
                        help="tempo used to calculate the first measure (default: 120)")
    args = parser.parse_args()
    if args.bpm <= 0:
        parser.error("--bpm must be greater than zero")

    paths = select_files(args.files)
    events = load_track_events(paths)
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
            for i, track_events in enumerate(events):
                events[i] = [
                    (t - bar_seconds, kind, note, velocity)
                    for t, kind, note, velocity in track_events
                    if t >= bar_seconds
                ]
            print(f"Skipping events in the first 4/4 bar ({bar_seconds:.2f} s at {args.bpm:g} BPM).")

        print(f"Partial test mode: {len(devices)} Joy-Con(s).")
        print("Routing: J1=A/B; J2=C; J3=D; J4=E")
        print("Experimental rumble encoding; press Ctrl+C to stop.")
        start = time.perf_counter()
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
                        active[i][note] = (note_frequency(note), velocity_amplitude(velocity))
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
                    low_note = next(iter(active[low_idx].values()), None)
                    high_note = next(iter(active[high_idx].values()), None)
                    low_freq, low_amp = low_note if low_note else (120.0, 0.0)
                    high_freq, high_amp = high_note if high_note else (200.0, 0.0)
                    payload = make_rumble(low_freq, low_amp, high_freq, high_amp)
                    device.send(payload, payload)
            time.sleep(0.001)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        for device in reversed(connected):
            device.close()
    print("Playback finished.")


if __name__ == "__main__":
    main()
