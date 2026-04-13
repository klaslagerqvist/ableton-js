from __future__ import absolute_import
import json

import Live

from .Config import DEBUG
from .Interface import Interface
from .Logging import logger


def _coerce_new_note_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return bool(value)


def _normalize_new_note_spec(raw):
    """Note spec for ``add_new_notes`` per Live Object Model (Clip).

    Spec: one argument ``dict`` with key ``notes`` → list of note dicts; each note has
    required ``pitch`` (int), ``start_time`` / ``duration`` (float), optional ``velocity``,
    ``mute``, ``probability``, ``velocity_deviation``, ``release_velocity``.

    https://docs.cycling74.com/apiref/lom/clip/#add_new_notes

    Coerces JSON/scalar types and drops optional keys when they match LOM defaults so
    the embedded API sees plain int/float/bool (not strings).
    """
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError("add_new_notes: each note must be a dict")
    pitch = int(raw["pitch"])
    start_time = float(raw["start_time"])
    duration = float(raw["duration"])
    spec = {
        "pitch": pitch,
        "start_time": start_time,
        "duration": duration,
    }
    if "velocity" in raw and raw["velocity"] is not None:
        v = float(raw["velocity"])
        if abs(v - 100.0) > 1e-9:
            spec["velocity"] = v
    if _coerce_new_note_bool(raw.get("mute")):
        spec["mute"] = True
    if "probability" in raw and raw["probability"] is not None:
        p = float(raw["probability"])
        if abs(p - 1.0) > 1e-9:
            spec["probability"] = p
    if "velocity_deviation" in raw and raw["velocity_deviation"] is not None:
        vd = float(raw["velocity_deviation"])
        if abs(vd) > 1e-9:
            spec["velocity_deviation"] = vd
    if "release_velocity" in raw and raw["release_velocity"] is not None:
        rv = float(raw["release_velocity"])
        if abs(rv - 64.0) > 1e-9:
            spec["release_velocity"] = rv
    return spec


def _normalize_new_notes_list(notes):
    if isinstance(notes, str):
        notes = json.loads(notes)
    if not isinstance(notes, list):
        raise ValueError("add_new_notes: notes must be a list")
    return [_normalize_new_note_spec(n) for n in notes]


def _midi_note_spec_from_dict(d):
    """Python API uses ``Live.Clip.MidiNoteSpecification``, not plain dicts (LOM note dicts are for Max/JS).

    Same pattern as AbletonOSC ``clip_add_notes``:
    https://github.com/ideoforms/AbletonOSC/blob/master/abletonosc/clip.py
    """
    pitch = int(d["pitch"])
    start_time = float(d["start_time"])
    duration = float(d["duration"])
    velocity = float(d["velocity"]) if "velocity" in d else 100.0
    mute = bool(d.get("mute", False))
    base = {
        "pitch": pitch,
        "start_time": start_time,
        "duration": duration,
        "velocity": velocity,
        "mute": mute,
    }
    extra = {}
    if "probability" in d:
        extra["probability"] = float(d["probability"])
    if "velocity_deviation" in d:
        extra["velocity_deviation"] = float(d["velocity_deviation"])
    if "release_velocity" in d:
        extra["release_velocity"] = float(d["release_velocity"])
    try:
        return Live.Clip.MidiNoteSpecification(**base, **extra)
    except TypeError:
        if extra:
            return Live.Clip.MidiNoteSpecification(**base)
        raise


class Clip(Interface):
    @staticmethod
    def serialize_clip(clip):
        if clip is None:
            return None

        clip_id = Interface.save_obj(clip)
        return {
            "id": clip_id,
            "name": clip.name,
            "color": clip.color,
            "color_index": clip.color_index,
            "is_audio_clip": clip.is_audio_clip,
            "is_midi_clip": clip.is_midi_clip,
            "start_time": clip.start_time,
            "end_time": clip.end_time,
            "muted": clip.muted
        }

    def __init__(self, c_instance, socket):
        super(Clip, self).__init__(c_instance, socket)

    def get_notes(self, ns, from_time=0, from_pitch=0, time_span=99999999999999, pitch_span=128):
        return ns.get_notes(from_time, from_pitch, time_span, pitch_span)

    def get_notes_extended(self, ns, from_time=0, from_pitch=0, time_span=99999999999999, pitch_span=128):
        midi_note_vector = ns.get_notes_extended(from_pitch, pitch_span, float(from_time), float(time_span))
        return [
            {
                "duration": note.duration,
                "mute": note.mute,
                "note_id": note.note_id,
                "pitch": note.pitch,
                "probability": note.probability,
                "release_velocity": note.release_velocity,
                "start_time": note.start_time,
                "velocity": note.velocity,
                "velocity_deviation": note.velocity_deviation
            }
            for note in midi_note_vector
        ]
        
    def apply_note_modifications(self, ns, notes):
        existing_notes = ns.get_notes_extended(0, 128, 0, 99999999999999)
        existing_notes_map = {note.note_id: note for note in existing_notes}
        
        for modified_note_data in notes:
            note_id = modified_note_data.get("note_id")
            if note_id is None:
                raise ValueError("The note_id parameter is required to modify the note.")
            if note_id in existing_notes_map:
                note_to_update = existing_notes_map[note_id]
                for key, value in modified_note_data.items():
                    if key != "note_id" and hasattr(note_to_update, key):
                        setattr(note_to_update, key, value)
        
        return ns.apply_note_modifications(existing_notes)

    def add_new_notes(self, ns, notes):
        #normed = _normalize_new_notes_list(notes)
        #specs = tuple(_midi_note_spec_from_dict(d) for d in normed)
        #if DEBUG:
        #    logger.info("AbletonJS add_new_notes count=%s specs=%r", len(specs), specs)

        specs = []

        for note in notes:
            specs.append(Live.Clip.MidiNoteSpecification(start_time=note["start_time"],
                                                       duration=note["duration"],
                                                       pitch=note["pitch"],
                                                       velocity=note["velocity"],
                                                       mute=note["mute"]))
        return ns.add_new_notes(tuple(specs))

    def get_warp_markers(self, ns):
        dict_markers = []
        for warp_marker in ns.warp_markers:
            dict_markers.append({
                "beat_time": warp_marker.beat_time,
                "sample_time": warp_marker.sample_time,
            })
        return dict_markers

    def set_notes(self, ns, notes):
        return ns.set_notes(tuple(notes))

    def replace_selected_notes(self, ns, notes):
        return ns.replace_selected_notes(tuple(notes))
        