from enum import Enum, auto
from typing import Optional
import time

from ..observer_base import ObserverBase
from .single_text_line_animated import SingleTextLineAnimatedObserver
from observer_states import ObserverStates

_FINISHED_STATES = frozenset([ObserverStates.ANIMATION_FINISHED, ObserverStates.IDLE])

FIELD_LABELS = {"artist": "Artist", "title": "Title", "album": "Album"}
DEFAULT_FIELDS = ("artist", "title", "album")


class _State(Enum):
    ANIMATING = auto()
    PAUSING   = auto()
    IDLE      = auto()


class KeyValueTextObserver(ObserverBase):
    """Cycles through the configured song fields (artist/title/album) and any
    active custom messages on two displays:
        key_driver   (8-char)  — label:  'Artist', 'Title', 'Album', or a message title
        value_driver (12-char) — value:  the corresponding text

    The between-pair pause uses key_driver.delay_after_animation_finished_s.
    Album is only included in the cycle when non-empty. Custom messages
    (added via Coordinator.add_message) are appended after the song fields
    and keep cycling — even with nothing playing — until removed or expired.

    `fields` (kwarg) selects which song fields to show and in what order —
    defaults to ('artist', 'title', 'album'). Coordinator always delivers a
    new song as artist, then album (if any), then title, in that order — so
    the cycle is (re)built and shown once title lands, which is always last,
    rather than trying to show each field the instant it arrives.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__()
        if "key_driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'key_driver'")
        self._key_driver: SingleTextLineAnimatedObserver = kwargs['key_driver']
        self._key_driver.auto_loop = False

        if "value_driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'value_driver'")
        self._value_driver: SingleTextLineAnimatedObserver = kwargs['value_driver']
        self._value_driver.auto_loop = False

        fields = kwargs.get('fields', DEFAULT_FIELDS)
        unknown = [f for f in fields if f not in FIELD_LABELS]
        if unknown:
            raise ValueError(f"Unknown display field(s) {unknown}; valid fields are {tuple(FIELD_LABELS)}")
        self._fields: list[str] = list(fields)

        self._values: dict[str, str] = {"artist": "", "title": "", "album": ""}
        self._cycle: list[tuple[str, str]] = []
        self._kv_state: _State = _State.IDLE
        self._pause_until: float = 0.0

    @property
    def _between_pair_delay_s(self) -> float:
        return self._key_driver.delay_after_animation_finished_s

    def _build_cycle(self) -> list[tuple[str, str]]:
        self._purge_expired_messages()
        cycle: list[tuple[str, str]] = []
        if self._values["artist"] or self._values["title"]:
            for field in self._fields:
                value = self._values[field]
                if field == "album" and not value:
                    continue
                cycle.append((FIELD_LABELS[field], value))
        cycle.extend((m.title, m.text) for m in self._message_rotation)
        return cycle

    def _show_pair(self, label: str, value: str) -> None:
        self._key_driver.Value = label
        self._value_driver.Value = value
        self._kv_state = _State.ANIMATING

    def _update_cycle_entry(self, label: str, value: str) -> None:
        """Update an existing cycle entry in place, or append if not present.
        If value is empty or whitespace, remove the entry from the cycle."""
        value = value.strip() if value else ""
        if not value:
            self._cycle = [(l, v) for l, v in self._cycle if l != label]
            return
        for i, (lbl, _) in enumerate(self._cycle):
            if lbl == label:
                self._cycle[i] = (label, value)
                return
        self._cycle.append((label, value))

    def _go_idle_or_resume_messages(self) -> None:
        """Go idle, unless there are still active rotation messages to show —
        in that case resume the cycle immediately instead of waiting for a
        song to start it back up."""
        self._purge_expired_messages()
        self._cycle = []
        if self._message_rotation:
            self._kv_state = _State.PAUSING
            self._pause_until = time.monotonic()
        else:
            self._kv_state = _State.IDLE

    def _reset_song_and_resume_messages(self) -> None:
        """Clear the current song and drop back to idle (or straight back
        into the message rotation, if anything's still active there)."""
        self._values = {"artist": "", "title": "", "album": ""}
        self._go_idle_or_resume_messages()
        self._key_driver._driver.clear()
        self._value_driver._driver.clear()

    # ------------------------------------------------------------------
    # ObserverBase hooks
    # ------------------------------------------------------------------

    def updated_artist(self, artist: str, **kwargs) -> None:
        self._values["artist"] = artist
        # Clear album — a new track is starting and album hasn't arrived
        # yet. If an ALBUM update follows, it lands before title (below).
        self._values["album"] = ""

    def updated_song_title(self, song_title: str, **kwargs) -> None:
        self._values["title"] = song_title
        # Title is always the last field Coordinator delivers for a new
        # song (artist, then album if any, then title) — so this is the
        # point at which the full set of fields for the song is known.
        # Interrupt whatever's currently showing and start the new cycle.
        self._cycle = self._build_cycle()
        if self._cycle:
            self._show_pair(*self._cycle.pop(0))
        else:
            self._go_idle_or_resume_messages()

    def updated_album(self, album: str, **kwargs) -> None:
        self._values["album"] = (album or '').strip()
        if "album" in self._fields:
            self._update_cycle_entry("Album", self._values["album"])

    def playback_stopped(self, **kwargs) -> None:
        self._reset_song_and_resume_messages()

    def timeout_expired(self) -> None:
        self._reset_song_and_resume_messages()

    def on_messages_changed(self) -> None:
        # A message was added/updated while nothing was playing — kick the
        # rotation out of IDLE so it shows on the next draw() instead of
        # waiting for a song to start.
        if self._kv_state == _State.IDLE:
            self._go_idle_or_resume_messages()

    # ------------------------------------------------------------------
    # Coordinator-facing API
    # ------------------------------------------------------------------

    def next_wakeup(self) -> Optional[float]:
        if self._kv_state == _State.PAUSING:
            # Once the pause window elapses we must wake up immediately to
            # advance to the next pair — the key/value drivers are idle at
            # this point (auto_loop=False) and would otherwise report no
            # wakeup needed, stalling the rotation until an unrelated event
            # wakes the coordinator.
            remaining = self._pause_until - time.monotonic()
            return max(0.0, remaining)
        key_wake = self._key_driver.next_wakeup()
        val_wake = self._value_driver.next_wakeup()
        candidates = [t for t in (key_wake, val_wake) if t is not None]
        return min(candidates) if candidates else None

    def draw(self) -> None:
        if self._kv_state == _State.IDLE:
            # Still drive the sub-drivers even with nothing new to show:
            # next_wakeup() below queries them unconditionally (it has to,
            # e.g. so a message added while idle can wake the rotation
            # back up), so a driver left mid-animation here -- most
            # notably a clear animation that didn't finish before this
            # observer went idle -- would report "wake immediately"
            # forever with nothing ever calling draw() to let it actually
            # finish, busy-looping the coordinator thread. Each driver's
            # own draw() already no-ops instantly once truly idle, so this
            # costs nothing once settled.
            self._key_driver.draw()
            self._value_driver.draw()
            return

        if self._kv_state == _State.PAUSING:
            if time.monotonic() < self._pause_until:
                return
            if not self._cycle:
                self._cycle = self._build_cycle()
            if not self._cycle:
                # Nothing left to show (e.g. the last rotation message expired
                # with no song playing) — go idle until something new arrives.
                self._go_idle_or_resume_messages()
                self._key_driver._driver.clear()
                self._value_driver._driver.clear()
                return
            label, value = self._cycle.pop(0)
            self._show_pair(label, value)

        self._key_driver.draw()
        self._value_driver.draw()

        if (self._kv_state == _State.ANIMATING
                and self._key_driver._state in _FINISHED_STATES
                and self._value_driver._state in _FINISHED_STATES):
            self._kv_state = _State.PAUSING
            self._pause_until = time.monotonic() + self._between_pair_delay_s
