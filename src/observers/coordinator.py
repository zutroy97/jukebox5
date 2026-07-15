import logging
import queue
import threading
import time
from typing import Callable, Optional

from panel.panel_input_base import JukeboxPanelInputBase, JukeboxPanelOutputBase
from .observer_base import ObserverBase, UpdateEventType


class _TrackSelector:
    """Accumulates digits (or a 'P'-prefixed command) typed on the panel.

    Only ever touched from the Coordinator's own thread (via `_enqueue` and
    the `_loop` polling below), so it needs no locking of its own.

    The first keypress after idle decides the mode:
      - a digit  starts a 3-digit track selection (SELECTION_TIMEOUT_S
                 between keystrokes)
      - 'P'      starts command entry (COMMAND_TIMEOUT_S between
                 keystrokes, shorter -- commands are meant to be entered
                 in one quick burst): subsequent keys are matched against
                 COMMANDS as they arrive. An exact match fires
                 immediately (on_command(COMMANDS[entered]) and the valid
                 feedback below) without waiting for the timeout; a
                 sequence no full command starts with is invalid
                 immediately, same idea.

    Track selection calls on_selection_complete(entered) once 3 digits are
    in, and its bool return value (True = a real match -- currently a
    playlist track) selects one of two feedback sequences before the
    display reverts to whatever it was showing before entry started:
      - valid:   the entered code blinks blink_count times (blink_phase_s
                 per on/off phase)
      - invalid: error_text is shown for error_duration_s
    Command entry uses the same feedback -- valid always for an exact
    COMMANDS match (nothing else calls on_command), invalid for an
    unmatchable sequence.

    Feedback is driven by the same `_deadline`/`_feedback_queue` machinery
    entry-timeout uses, just repurposed once entry completes -- see
    check_timeout(). Timing/text defaults match config.py's
    TrackSelectionFeedbackConfig; see Coordinator for where config values
    actually get here.
    """

    DIGIT_COUNT: int = 3
    SELECTION_TIMEOUT_S: float = 10.0
    COMMAND_TIMEOUT_S: float = 2.0

    # Entered sequence (including the leading 'P') -> shairport-sync remote
    # command name (see ShairportSyncMQTTSource.send_remote_command).
    COMMANDS: dict[str, str] = {
        "PP": "playpause",
        "P111": "previtem",
        "P666": "nextitem",
    }

    def __init__(
        self,
        panel_display: JukeboxPanelOutputBase,
        on_selection_complete: Callable[[str], bool],
        on_command: Callable[[str], None],
        get_idle_text: Callable[[], str],
        get_idle_right_led: Callable[[], bool],
        blink_count: int = 3,
        blink_phase_s: float = 0.25,
        error_text: str = "Err",
        error_duration_s: float = 2.0,
    ) -> None:
        self._panel_display = panel_display
        self._on_selection_complete = on_selection_complete
        self._on_command = on_command
        self._get_idle_text = get_idle_text
        self._get_idle_right_led = get_idle_right_led
        self._blink_count = blink_count
        self._blink_phase_s = blink_phase_s
        self._error_text = error_text
        self._error_duration_s = error_duration_s
        self._digits: str = ""
        self._mode: Optional[str] = None  # 'track' | 'command', while entering
        self._deadline: Optional[float] = None
        # Queue of (duration_s, text) phases still to show for the
        # post-entry blink/error feedback sequence; None text means blank.
        # Empty except during that sequence.
        self._feedback_queue: list[tuple[float, Optional[str]]] = []

    def is_active(self) -> bool:
        return self._deadline is not None

    def button_pressed(self, key: str) -> None:
        if self._feedback_queue:
            return  # ignore input while a blink/error sequence plays out
        if key == 'R':
            self._reset()
            return

        if self._mode is None:
            if key == 'P':
                self._mode = 'command'
            elif key in "0123456789":
                self._mode = 'track'
            else:
                return
            # The display can only show one thing at a time -- current
            # selection or entry-in-progress -- so the two LEDs are
            # mutually exclusive: entering something means the display
            # is no longer showing the current selection, so that LED
            # goes off for the duration.
            self._panel_display.LeftLedSet(True)  # "Selections being made"
            self._panel_display.RightLedSet(False)  # "Selection Playing"
        elif self._mode == 'command':
            if key != 'P' and key not in "0123456789":
                return
        else:  # 'track'
            if key not in "0123456789":
                return

        self._digits += key
        timeout = self.COMMAND_TIMEOUT_S if self._mode == 'command' else self.SELECTION_TIMEOUT_S
        self._deadline = time.monotonic() + timeout
        # Not animated: this fires once per keystroke, faster than a
        # segment reveal could complete -- an animated driver would just
        # show a perpetually-interrupted reveal instead of crisp echo.
        self._panel_display.WriteToFourDigitDisplay(self._digits.ljust(4), animated=False)

        if self._mode == 'track':
            if len(self._digits) < self.DIGIT_COUNT:
                return
            entered = self._digits
            self._finish_entry()
            is_valid = self._on_selection_complete(entered)
            self._start_feedback(entered, is_valid)
            return

        # 'command' mode: fire as soon as there's an exact match, bail out
        # as soon as no command could possibly match what's typed so far --
        # no need to wait out the timeout in either case.
        command = self.COMMANDS.get(self._digits)
        if command is not None:
            entered = self._digits
            self._finish_entry()
            self._on_command(command)
            self._start_feedback(entered, True)
        elif not any(c.startswith(self._digits) for c in self.COMMANDS):
            entered = self._digits
            self._finish_entry()
            self._start_feedback(entered, False)

    def _finish_entry(self) -> None:
        self._digits = ""
        self._mode = None
        self._panel_display.LeftLedSet(False)  # entry is over, made or not

    def _start_feedback(self, entered: str, is_valid: bool) -> None:
        if is_valid:
            on_off = (self._blink_phase_s, entered.ljust(4)), (self._blink_phase_s, None)
            self._feedback_queue = list(on_off) * self._blink_count
        else:
            self._feedback_queue = [(self._error_duration_s, self._error_text.ljust(4))]
        self._advance_feedback()

    def _advance_feedback(self) -> None:
        duration, text = self._feedback_queue.pop(0)
        # Not animated: the blink/error phases have exact, short timing
        # (as fast as blink_phase_s) that a segment reveal would blow
        # straight through, turning a crisp blink into a smear.
        self._panel_display.WriteToFourDigitDisplay(text if text is not None else ' ' * 4, animated=False)
        self._deadline = time.monotonic() + duration

    def next_wakeup(self) -> Optional[float]:
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())

    def check_timeout(self) -> None:
        if self._deadline is None or time.monotonic() < self._deadline:
            return
        if self._feedback_queue:
            self._advance_feedback()
        else:
            self._reset()

    def _reset(self) -> None:
        self._digits = ""
        self._mode = None
        self._deadline = None
        self._feedback_queue = []
        self._panel_display.LeftLedSet(False)  # "Selections being made"
        # Resume showing the currently-playing track's number (and its
        # matching LED state) rather than going blank -- a
        # completed/cancelled/timed-out selection doesn't take effect until
        # the queued track actually starts playing (which only happens
        # later, once shairport-sync reports the track_id change over
        # MQTT), so the old number/state is still accurate here.
        self._panel_display.WriteToFourDigitDisplay(self._get_idle_text())
        self._panel_display.RightLedSet(self._get_idle_right_led())  # "Selection Playing"


class Coordinator:
    """Owns the single background thread that all observer I/O runs on.

    Every public method below is thread-safe: it just packages the call as a
    zero-argument closure and drops it on `_event_queue`. The coordinator
    thread (`_loop`) is the only thread that ever calls a closure, notifies
    observers, or draws them — this keeps I2C/serial access single-threaded
    without every caller having to reason about locking.
    """

    TimeoutLimitInSeconds: int = 30 * 60

    def __init__(self, **kwargs) -> None:
        self._logger = logging.getLogger(__class__.__name__)
        self.observers: list[ObserverBase] = []
        self._observers_lock = threading.RLock()
        self.IsRunning: bool = True
        self._timeout: float = time.monotonic() + Coordinator.TimeoutLimitInSeconds
        self._panelButton: JukeboxPanelInputBase = kwargs['panelButtons']
        self._panelDisplay: JukeboxPanelOutputBase = kwargs['panelDisplay']
        self._updateCount: int = 0
        self._current_track_text: str = ' ' * 4
        self._current_is_known_track: bool = False
        self._is_paused: bool = False
        self._flash_on: bool = True
        self._flash_interval_s: float = kwargs.get('flash_interval_s', 0.75)
        self._flash_deadline: Optional[float] = None

        on_selection_complete = kwargs.get('on_selection_complete', lambda entered: False)
        on_command = kwargs.get('on_command', lambda command: None)
        self._track_selector = _TrackSelector(
            panel_display=self._panelDisplay,
            on_selection_complete=on_selection_complete,
            on_command=on_command,
            get_idle_text=lambda: self._current_track_text,
            get_idle_right_led=lambda: self._current_is_known_track,
            blink_count=kwargs.get('blink_count', 3),
            blink_phase_s=kwargs.get('blink_phase_s', 0.25),
            error_text=kwargs.get('error_text', "Err"),
            error_duration_s=kwargs.get('error_duration_s', 2.0),
        )

        self._event_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

        # Marshal the initial display update onto the coordinator thread too,
        # rather than calling it directly here — that would race with the
        # loop thread over the panel display's I2C access.
        self._enqueue(self.updateJukeboxDisplay)

    # ------------------------------------------------------------------
    # Observer management
    # ------------------------------------------------------------------

    def add_observer(self, observer: ObserverBase) -> None:
        with self._observers_lock:
            if observer not in self.observers:
                self.observers.append(observer)

    def remove_observer(self, observer: ObserverBase) -> None:
        with self._observers_lock:
            if observer in self.observers:
                self.observers.remove(observer)

    def _snapshot_observers(self) -> list[ObserverBase]:
        with self._observers_lock:
            return list(self.observers)

    # ------------------------------------------------------------------
    # Public thread-safe API — each call is just packaged as a closure and
    # handed to the coordinator thread.
    # ------------------------------------------------------------------

    def _enqueue(self, task: Callable[[], None]) -> None:
        self._event_queue.put(task)

    def update_song_info(self, artist: str, song_title: str, album: str = "") -> None:
        """Notify observers of a new track."""
        self._enqueue(lambda: self._apply_song_update(artist, song_title, album))

    def play_ended(self) -> None:
        """Notify observers that playback has stopped and the display should clear."""
        self._enqueue(self._apply_play_ended)

    def add_message(self, title: str, text: str, ttl_s: float = 0, display_s: float = 5) -> None:
        """Add or update a custom message in the display rotation.

        Args:
            title:     Unique identifier for the message (shown as the label).
            text:      Message body (shown as the value).
            ttl_s:     Seconds until the message is automatically removed.
                       0 means the message persists until explicitly removed.
            display_s: Seconds the message is held on screen after its animation
                       completes before advancing to the next item in the cycle.
        """
        self._enqueue(lambda: self._apply_message(title, text, ttl_s, display_s))

    # update_message is an alias: adding a message that already exists (by
    # title) replaces it, so there's no separate code path needed.
    update_message = add_message

    def remove_message(self, title: str) -> None:
        """Remove a custom message from the display rotation by title.
        No-op if the message is not present."""
        self._enqueue(lambda: self._apply_message(title, text=None, ttl_s=0, display_s=0))

    def display_track_number(self, text: str, is_known_track: bool) -> None:
        """Write a value to the four-digit panel display, and remember it
        as the value _TrackSelector._reset() restores once digit entry
        exits (see get_idle_text above). is_known_track drives the right
        LED ("Selection Playing"): on exactly when the currently-playing
        track was actually found in the playlist (i.e. `text` is a real
        index rather than the "unknown track" placeholder)."""
        self._enqueue(lambda: self._apply_track_number(text, is_known_track))

    def _apply_track_number(self, text: str, is_known_track: bool) -> None:
        self._current_track_text = text
        self._current_is_known_track = is_known_track
        # Cache unconditionally so _reset() picks up the right value once
        # entry ends, but don't touch the display/LED live while the user
        # is mid-entry -- a track actually changing at that moment
        # shouldn't clobber the digits they're typing.
        if not self._track_selector.is_active():
            self._panelDisplay.RightLedSet(is_known_track)
            self._refresh_track_display()

    def clear_for_inactive(self) -> None:
        """Notify the coordinator that shairport-sync reports active_end
        (no session, idle past active_state_timeout) -- clear the panel's
        digit displays and show a static 'Playback' / 'stopped' status on
        the label displays instead of the last-known artist/title."""
        self._enqueue(self._apply_active_end)

    def _apply_active_end(self) -> None:
        self._apply_pause_state(False)
        self._current_track_text = ' ' * 4
        self._current_is_known_track = False
        if not self._track_selector.is_active():
            self._panelDisplay.Clear()
            self._panelDisplay.RightLedSet(False)
        self._apply_message("Playback", "stopped", ttl_s=0, display_s=5)

    def set_playback_paused(self, is_paused: bool) -> None:
        """Notify the coordinator that playback has paused/resumed. While
        paused, the 4-digit track-number display flashes on/off
        (flash_interval_s per phase) instead of showing the number
        steadily."""
        self._enqueue(lambda: self._apply_pause_state(is_paused))

    def _apply_pause_state(self, is_paused: bool) -> None:
        self._is_paused = is_paused
        self._flash_on = True
        self._flash_deadline = time.monotonic() + self._flash_interval_s if is_paused else None
        self._refresh_track_display()

    def _refresh_track_display(self) -> None:
        # A selection-in-progress owns the 4-digit display -- don't clobber
        # the digits the user is typing.
        if self._track_selector.is_active():
            return
        if self._is_paused:
            # Not animated: flash phases need exact, crisp on/off timing --
            # a segment reveal would eat into flash_interval_s and blur the
            # toggle into a slow re-materialize instead of a crisp blink
            # (same reasoning as _TrackSelector's blink/error feedback).
            text = self._current_track_text if self._flash_on else ' ' * 4
            self._panelDisplay.WriteToFourDigitDisplay(text, animated=False)
        else:
            self._panelDisplay.WriteToFourDigitDisplay(self._current_track_text)

    def _check_flash_timeout(self) -> None:
        if self._flash_deadline is None or time.monotonic() < self._flash_deadline:
            return
        self._flash_on = not self._flash_on
        self._flash_deadline = time.monotonic() + self._flash_interval_s
        self._refresh_track_display()

    def on_button_press(self, key: str) -> None:
        """Feed a raw panel button press ('0'-'9', 'R', 'P') into track selection."""
        self._enqueue(lambda: self._track_selector.button_pressed(key))

    def shutdown(self, message: str = "Shutting down coordinator") -> None:
        """Shut down the coordinator loop cleanly and wait for it to exit."""
        self._enqueue(lambda: self._apply_shutdown(message))
        self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Internal — runs entirely on the coordinator thread
    # ------------------------------------------------------------------

    def _apply_song_update(self, artist: str, song_title: str, album: str = "") -> None:
        # Real playback has resumed -- drop any lingering "Playback" /
        # "stopped" status from clear_for_inactive() so it doesn't keep
        # reappearing in the message rotation alongside the actual song.
        self._apply_message("Playback", text=None, ttl_s=0, display_s=0)
        self._notify_all(UpdateEventType.ARTIST, artist)
        if album and album.strip():
            self._notify_all(UpdateEventType.ALBUM, album.strip())
        self._notify_all(UpdateEventType.SONG_TITLE, song_title)
        self._updateCount += 1
        self.updateJukeboxDisplay()
        self._timeout = time.monotonic() + Coordinator.TimeoutLimitInSeconds

    def _apply_play_ended(self) -> None:
        self._notify_all(UpdateEventType.STATE_PLAYBACK_STOPPED, '')
        self._notify_all(UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT, '')
        # Playback has stopped entirely (not just paused) -- stop flashing.
        self._apply_pause_state(False)

    def _apply_message(self, title: str, text: str | None, ttl_s: float, display_s: float) -> None:
        for observer in self._snapshot_observers():
            observer.UpdateReceived(
                update_type=UpdateEventType.CUSTOM_MESSAGE,
                title=title,
                text=text,
                ttl_s=ttl_s,
                display_s=display_s,
            )

    def _apply_shutdown(self, message: str) -> None:
        self.IsRunning = False
        for observer in self._snapshot_observers():
            observer.shutdown(message=message)

    def _notify_all(self, update_type: UpdateEventType, value: str) -> None:
        for observer in self._snapshot_observers():
            observer.UpdateReceived(update_type=update_type, value=value)

    def _next_wakeup(self) -> float:
        deadlines: list[float] = []

        remaining_timeout = self._timeout - time.monotonic()
        if remaining_timeout > 0:
            deadlines.append(remaining_timeout)

        selection_wakeup = self._track_selector.next_wakeup()
        if selection_wakeup is not None:
            deadlines.append(selection_wakeup)

        if self._flash_deadline is not None:
            deadlines.append(max(0.0, self._flash_deadline - time.monotonic()))

        for observer in self._snapshot_observers():
            w = observer.next_wakeup()
            if w is not None:
                deadlines.append(w)

        return max(0.0, min(deadlines)) if deadlines else 1.0

    def _loop(self) -> None:
        while self.IsRunning:
            sleep_for = self._next_wakeup()

            try:
                task = self._event_queue.get(timeout=sleep_for)
            except queue.Empty:
                task = None

            if task is not None:
                task()
                if not self.IsRunning:
                    return

            if time.monotonic() >= self._timeout:
                self._notify_all(UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT, '')
                self._timeout = time.monotonic() + Coordinator.TimeoutLimitInSeconds

            self._track_selector.check_timeout()
            self._check_flash_timeout()

            for observer in self._snapshot_observers():
                observer.draw()

    def updateJukeboxDisplay(self) -> None:
        self._panelDisplay.WriteToThreeDigitDisplay(str(self._updateCount).rjust(3))
