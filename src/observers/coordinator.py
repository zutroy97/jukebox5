import logging
import queue
import threading
import time

from panel.panel_input_base import JukeboxPanelInputBase, JukeboxPanelOutputBase
from .observer_base import ObserverBase, UpdateEventType


class Coordinator:
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

        # All public methods marshal work onto this queue so that
        # observer.draw() and observer.UpdateReceived() always run on the
        # coordinator thread — keeping I2C access single-threaded.
        self._event_queue: queue.Queue = queue.Queue()

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

        # Marshal the initial display update onto the coordinator thread via
        # the queue too, rather than calling updateJukeboxDisplay() directly
        # from whichever thread constructs the Coordinator — that would race
        # with the loop thread over the panel display's I2C access.
        self._event_queue.put(('update_display',))

    # ------------------------------------------------------------------
    # Observer management
    # ------------------------------------------------------------------

    def add_observer(self, observer: ObserverBase):
        with self._observers_lock:
            if observer not in self.observers:
                self.observers.append(observer)

    def remove_observer(self, observer: ObserverBase):
        with self._observers_lock:
            if observer in self.observers:
                self.observers.remove(observer)

    # ------------------------------------------------------------------
    # Public thread-safe API
    # ------------------------------------------------------------------

    def update_song_info(self, artist: str, song_title: str, album: str = "") -> None:
        """Notify observers of a new track."""
        self._event_queue.put(('song', artist, song_title, album))

    def play_ended(self) -> None:
        """Notify observers that playback has stopped and the display should clear."""
        self._event_queue.put(('play_end',))

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
        self._event_queue.put(('message_add', title, text, ttl_s, display_s))

    def remove_message(self, title: str) -> None:
        """Remove a custom message from the display rotation by title.
        No-op if the message is not present."""
        self._event_queue.put(('message_remove', title))

    def update_message(self, title: str, text: str, ttl_s: float = 0, display_s: float = 5) -> None:
        """Update the text and/or TTL of an existing message.
        If the message does not exist it is created (same behaviour as add_message)."""
        self._event_queue.put(('message_add', title, text, ttl_s, display_s))

    def shutdown(self, message: str = "Shutting down coordinator") -> None:
        """Shut down the coordinator loop cleanly."""
        self._event_queue.put(('shutdown', message))
        self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Internal — runs entirely on the coordinator thread
    # ------------------------------------------------------------------

    def _apply_song_update(self, artist: str, song_title: str, album: str = "") -> None:
        self._notify(UpdateEventType.ARTIST, artist)
        if album and album.strip():
            self._notify(UpdateEventType.ALBUM, album.strip())
        self._notify(UpdateEventType.SONG_TITLE, song_title)
        self._updateCount += 1
        self.updateJukeboxDisplay()
        self._timeout = time.monotonic() + Coordinator.TimeoutLimitInSeconds

    def _apply_add_message(self, title: str, text: str, ttl_s: float, display_s: float) -> None:
        with self._observers_lock:
            snapshot = list(self.observers)
        for observer in snapshot:
            observer.UpdateReceived(
                update_type=UpdateEventType.CUSTOM_MESSAGE,
                title=title,
                text=text,
                mesg_ttl_s=ttl_s,
                mesg_display_s=display_s,
            )

    def _apply_remove_message(self, title: str) -> None:
        with self._observers_lock:
            snapshot = list(self.observers)
        for observer in snapshot:
            observer.UpdateReceived(
                update_type=UpdateEventType.CUSTOM_MESSAGE,
                title=title,
                text=None,   # None signals removal per ObserverBase._handle_message
            )

    def _notify(self, update_type: UpdateEventType, value: str) -> None:
        with self._observers_lock:
            snapshot = list(self.observers)
        for observer in snapshot:
            observer.UpdateReceived(update_type=update_type, value=value)

    def _next_wakeup(self) -> float:
        deadlines: list[float] = []

        remaining_timeout = self._timeout - time.monotonic()
        if remaining_timeout > 0:
            deadlines.append(remaining_timeout)

        with self._observers_lock:
            snapshot = list(self.observers)
        for observer in snapshot:
            w = observer.next_wakeup()
            if w is not None:
                deadlines.append(w)

        return max(0.0, min(deadlines)) if deadlines else 1.0

    def _loop(self) -> None:
        while self.IsRunning:
            sleep_for = self._next_wakeup()

            try:
                item = self._event_queue.get(timeout=sleep_for)
            except queue.Empty:
                item = None

            if item is not None:
                kind = item[0]
                if kind == 'song':
                    _, artist, song_title, album = item
                    self._apply_song_update(artist, song_title, album)
                elif kind == 'play_end':
                    self._notify(UpdateEventType.STATE_PLAYBACK_STOPPED, '')
                    self._notify(UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT, '')
                elif kind == 'message_add':
                    _, title, text, ttl_s, display_s = item
                    self._apply_add_message(title, text, ttl_s, display_s)
                elif kind == 'message_remove':
                    _, title = item
                    self._apply_remove_message(title)
                elif kind == 'update_display':
                    self.updateJukeboxDisplay()
                elif kind == 'shutdown':
                    _, message = item
                    self.IsRunning = False
                    with self._observers_lock:
                        snapshot = list(self.observers)
                    for observer in snapshot:
                        observer.shutdown(message=message)
                    return

            # Check idle timeout
            if time.monotonic() >= self._timeout:
                self._notify(UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT, '')
                self._timeout = time.monotonic() + Coordinator.TimeoutLimitInSeconds

            with self._observers_lock:
                snapshot = list(self.observers)
            for observer in snapshot:
                observer.draw()

    def updateJukeboxDisplay(self) -> None:
        x = self._updateCount % 2
        self._panelDisplay.LeftLedSet(x == 1)
        self._panelDisplay.RightLedSet(x == 0)
        self._panelDisplay.WriteToThreeDigitDisplay(str(self._updateCount))
        