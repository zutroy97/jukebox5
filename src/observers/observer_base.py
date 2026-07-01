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


@dataclass
class RotationMessage:
    """A message that participates in the display rotation for a limited time."""
    title: str
    text: str
    expires_at: float        # monotonic time after which the message is purged
    display_s: float = 5.0  # how long to show the message after animation completes

    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.monotonic() >= self.expires_at


class ObserverBase(ABC):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._is_running: bool = True
        self.DisplayWidth: int = kwargs.get('display_width', 8)
        '''The width of the display in characters.'''
        self._message_rotation: list[RotationMessage] = []

    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        '''Called when an update is received'''
        # Purge any expired messages on every event.
        self._purge_expired_messages()

        if update_type == UpdateEventType.ARTIST:
            artist = kwargs.get('value', 'Unknown Artist')
            self.updated_artist(artist=artist, **kwargs)
        elif update_type == UpdateEventType.SONG_TITLE:
            song_title = kwargs.get('value', 'Unknown Song Title')
            self.updated_song_title(song_title=song_title, **kwargs)
        elif update_type is UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT:
            self.timeout_expired()
        elif update_type == UpdateEventType.ALBUM:
            album = kwargs.get("value", "")
            self.updated_album(album=album, **kwargs)
        elif update_type is UpdateEventType.CUSTOM_MESSAGE:
            self._handle_message(**kwargs)

    def _purge_expired_messages(self) -> None:
        before = len(self._message_rotation)
        self._message_rotation = [m for m in self._message_rotation if not m.is_expired()]
        purged = before - len(self._message_rotation)
        if purged:
            self._logger.debug("Purged %d expired message(s) from rotation", purged)

    def _handle_message(self, **kwargs) -> None:
        title = kwargs.get('title', None)
        if not title or not str(title).strip():
            self._logger.debug("CUSTOM_MESSAGE ignored: missing or empty title")
            return

        text = kwargs.get('text', None)

        if text is None:
            # Remove the message from the rotation if present.
            before = len(self._message_rotation)
            self._message_rotation = [m for m in self._message_rotation if m.title != title]
            removed = before - len(self._message_rotation)
            if removed:
                self._logger.debug("Removed message %r from rotation", title)
            else:
                self._logger.debug("CUSTOM_MESSAGE removal: %r not found in rotation", title)
            return

        if not isinstance(text, str):
            self._logger.debug("CUSTOM_MESSAGE ignored: text must be a str, got %r", type(text))
            return

        ttl_s = kwargs.get('mesg_ttl_s', 0)
        if not isinstance(ttl_s, (int, float)) or ttl_s < 0:
            self._logger.debug("CUSTOM_MESSAGE ignored: mesg_ttl_s must be a non-negative number")
            return

        display_s = kwargs.get('mesg_display_s', 5)
        if not isinstance(display_s, (int, float)) or display_s <= 0:
            self._logger.debug("CUSTOM_MESSAGE ignored: mesg_display_s must be a positive number")
            return

        expires_at = (time.monotonic() + ttl_s) if ttl_s > 0 else 0.0

        # Replace existing message with the same title, or append.
        for i, m in enumerate(self._message_rotation):
            if m.title == title:
                self._message_rotation[i] = RotationMessage(
                    title=title, text=text, expires_at=expires_at, display_s=display_s
                )
                self._logger.debug("Updated message %r in rotation", title)
                return

        self._message_rotation.append(
            RotationMessage(title=title, text=text, expires_at=expires_at, display_s=display_s)
        )
        self._logger.debug("Added message %r to rotation (ttl=%.0fs, display=%.0fs)", title, ttl_s, display_s)
        self.on_messages_changed()

    def on_messages_changed(self) -> None:
        """Called when the message rotation changes. Subclasses can override
        to trigger a display update immediately."""
        pass

    def updated_artist(self, artist: str, **kwargs) -> None:
        '''Called when the artist is updated'''
        pass

    def updated_album(self, album: str, **kwargs) -> None:
        '''Called when the album is updated'''
        pass

    def updated_song_title(self, song_title: str, **kwargs) -> None:
        '''Called when the song title is updated'''
        pass

    def shutdown(self, message: str, **kwargs) -> None:
        '''Called when a shutdown event is received'''
        self._is_running = False

    def timeout_expired(self):
        self._logger.debug("Timeout expired!")

    def next_wakeup(self) -> Optional[float]:
        '''Return seconds until this observer needs to be drawn, or None if idle.
        The coordinator uses this to sleep precisely rather than busy-polling.'''
        # Wake at the earliest message expiry if any messages have a TTL.
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
    