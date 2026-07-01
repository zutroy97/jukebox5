from enum import Enum
from abc import abstractmethod, ABC
import logging
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


class ObserverBase(ABC):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._is_running: bool = True
        self.DisplayWidth: int = kwargs.get('display_width', 8)
        '''The width of the display in characters.'''

    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        '''Called when an update is received'''
        if update_type == UpdateEventType.ARTIST:
            artist = kwargs.get('value', 'Unknown Artist')
            self.updated_artist(artist=artist, **kwargs)
        elif update_type == UpdateEventType.SONG_TITLE:
            song_title = kwargs.get('value', 'Unknown Song Title')
            self.updated_song_title(song_title=song_title, **kwargs)
        elif update_type is UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT:
            self.timeout_expired()
        elif update_type is UpdateEventType.CUSTOM_MESSAGE:
            self._handle_message(**kwargs)


    def _handle_message(self, **kwargs):
        mesg_title = kwargs.get('title', None)
        if mesg_title is None or str(mesg_title).strip() is '':
            return # Invalid state, log debug and ignore
        mesg_text = kwargs.get('text', None)
        if mesg_text is None:
            # TODO: Remove the message from the display rotation if present; otherwise ignore
            return
        # reject if mesg_text is not a str
        mesg_ttl_s = kwargs.get('mesg_ttl_s', 0) # How long before this message is purged
        # reject if mesg_ttl_s is not a positive int
        mesg_display_s = kwargs.get('mesg_display_s', 5) # How long the message is displayed after its animation is completed
        # reject if mesg_display_s is not a positive int
        # if made it here, add the message to rotation, making sure to remove it from the rotation after mesg_ttl_s seconds

    def updated_artist(self, artist: str, **kwargs) -> None:
        '''Called when the artist is updated'''
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
        return None

    @abstractmethod
    def draw(self) -> None:
        '''Called to draw the current state of the observer.'''
        pass
