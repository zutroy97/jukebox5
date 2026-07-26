from enum import Enum
from abc import abstractmethod, ABC
import logging
import time
from dataclasses import dataclass
from typing import Optional


class UpdateEventType(Enum):
    '''Defines the type of update received'''
    NOT_SPECIFIED = 0
    ARTIST = 1
    SONG_TITLE = 2
    PING = 3
    NO_EVENT_RECEIVED_TIMEOUT = 4
    '''No event has been received in the timeout period'''
    STATE_PLAYBACK_STOPPED = 5
    CUSTOM_MESSAGE = 6
    ALBUM = 7
    ADVANCE_DISPLAY = 8
    '''Skip immediately to the next item in the display rotation, without
    waiting out its normal pause/animation timing.'''


@dataclass
class RotationMessage:
    """A message that participates in the display rotation for a limited time."""
    title: str
    text: str
    expires_at: float       # monotonic time after which the message is purged, or 0 for never
    display_s: float = 5.0  # how long to show the message after animation completes

    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.monotonic() >= self.expires_at


class ObserverBase(ABC):
    """Base class for anything the Coordinator drives.

    Subclasses should NOT override `UpdateReceived` — override the small
    `updated_*` / `playback_stopped` / `timeout_expired` hooks below instead.
    That way the base class's bookkeeping (message-rotation purging and
    dispatch) always runs, and a subclass can't accidentally opt out of it
    just by forgetting to call `super().UpdateReceived(...)`.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._is_running: bool = True
        self.DisplayWidth: int = kwargs.get('display_width', 8)
        '''The width of the display in characters.'''
        self._message_rotation: list[RotationMessage] = []

    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        '''Called when an update is received. Do not override — see class docstring.'''
        self._purge_expired_messages()

        if update_type == UpdateEventType.ARTIST:
            self.updated_artist(artist=kwargs.get('value', 'Unknown Artist'), **kwargs)
        elif update_type == UpdateEventType.SONG_TITLE:
            self.updated_song_title(song_title=kwargs.get('value', 'Unknown Song Title'), **kwargs)
        elif update_type == UpdateEventType.ALBUM:
            self.updated_album(album=kwargs.get('value', ''), **kwargs)
        elif update_type == UpdateEventType.STATE_PLAYBACK_STOPPED:
            self.playback_stopped(**kwargs)
        elif update_type == UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT:
            self.timeout_expired()
        elif update_type == UpdateEventType.CUSTOM_MESSAGE:
            self._handle_message(**kwargs)
        elif update_type == UpdateEventType.ADVANCE_DISPLAY:
            self.advance_display()

    # ------------------------------------------------------------------
    # Message rotation — fully handled here so subclasses get it for free.
    # ------------------------------------------------------------------

    def _purge_expired_messages(self) -> None:
        before = len(self._message_rotation)
        self._message_rotation = [m for m in self._message_rotation if not m.is_expired()]
        if len(self._message_rotation) != before:
            self._logger.debug("Purged %d expired message(s) from rotation", before - len(self._message_rotation))

    def _handle_message(
        self,
        title: Optional[str] = None,
        text: Optional[str] = None,
        ttl_s: float = 0,
        display_s: float = 5,
        **_ignored,
    ) -> None:
        if not title or not str(title).strip():
            self._logger.debug("CUSTOM_MESSAGE ignored: missing or empty title")
            return

        if text is None:
            before = len(self._message_rotation)
            self._message_rotation = [m for m in self._message_rotation if m.title != title]
            if len(self._message_rotation) != before:
                self._logger.debug("Removed message %r from rotation", title)
            else:
                self._logger.debug("CUSTOM_MESSAGE removal: %r not found in rotation", title)
            return

        if not isinstance(text, str):
            self._logger.debug("CUSTOM_MESSAGE ignored: text must be a str, got %r", type(text))
            return
        if not isinstance(ttl_s, (int, float)) or ttl_s < 0:
            self._logger.debug("CUSTOM_MESSAGE ignored: ttl_s must be a non-negative number")
            return
        if not isinstance(display_s, (int, float)) or display_s <= 0:
            self._logger.debug("CUSTOM_MESSAGE ignored: display_s must be a positive number")
            return

        expires_at = (time.monotonic() + ttl_s) if ttl_s > 0 else 0.0
        message = RotationMessage(title=title, text=text, expires_at=expires_at, display_s=display_s)

        for i, existing in enumerate(self._message_rotation):
            if existing.title == title:
                self._message_rotation[i] = message
                break
        else:
            self._message_rotation.append(message)

        self._logger.debug("Message %r in rotation (ttl=%.0fs, display=%.0fs)", title, ttl_s, display_s)
        self.on_messages_changed(title=title, text=text)

    def on_messages_changed(self, title: Optional[str] = None, text: Optional[str] = None) -> None:
        """Called when a message is added or updated (not on removal or
        expiry), with the title/text that changed. Subclasses can override
        to react immediately — e.g. to interrupt whatever is currently
        showing so an urgent status message is seen right away, instead of
        waiting for it to reach its turn in the rotation."""
        pass

    # ------------------------------------------------------------------
    # Hooks for subclasses to override — UpdateReceived dispatches to these.
    # ------------------------------------------------------------------

    def updated_artist(self, artist: str, **kwargs) -> None:
        '''Called when the artist is updated'''
        pass

    def updated_album(self, album: str, **kwargs) -> None:
        '''Called when the album is updated'''
        pass

    def updated_song_title(self, song_title: str, **kwargs) -> None:
        '''Called when the song title is updated'''
        pass

    def playback_stopped(self, **kwargs) -> None:
        '''Called when playback has stopped and the display should clear'''
        pass

    def timeout_expired(self) -> None:
        '''Called when no event has been received in the timeout period'''
        self._logger.debug("Timeout expired!")

    def advance_display(self) -> None:
        '''Called to skip immediately to the next item in the display
        rotation (song field or active message), interrupting whatever's
        currently showing/animating. No-op by default -- only meaningful
        for observers that actually rotate through multiple items.'''
        pass

    def shutdown(self, message: str, **kwargs) -> None:
        '''Called when a shutdown event is received'''
        self._is_running = False

    # ------------------------------------------------------------------
    # Coordinator-facing API
    # ------------------------------------------------------------------

    def next_wakeup(self) -> Optional[float]:
        '''Return seconds until this observer needs to be drawn, or None if idle.
        The coordinator uses this to sleep precisely rather than busy-polling.'''
        deadlines = [
            m.expires_at - time.monotonic()
            for m in self._message_rotation
            if m.expires_at > 0
        ]
        return max(0.0, min(deadlines)) if deadlines else None

    @abstractmethod
    def draw(self) -> None:
        '''Called to draw the current state of the observer.'''
        pass
