import asyncio
from enum import Enum
from abc import abstractmethod, ABC
import logging

class UpdateEventType(Enum):
    '''Defines the type of update received'''
    ARTIST = 1
    SONG_TITLE = 2


class ObserverBase(ABC):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._is_running : bool = True

    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        '''Called when an update is received'''
        #print(f"Observer {self.__class__.__name__} received update of type {update_type}")
        if update_type == UpdateEventType.ARTIST:
            artist = kwargs.get('value', 'Unknown Artist')
            self.updated_artist(artist=artist, **kwargs)
        elif update_type == UpdateEventType.SONG_TITLE:
            song_title = kwargs.get('value', 'Unknown Song Title')
            self.updated_song_title(song_title=song_title, **kwargs)

    def updated_artist(self, artist: str, **kwargs) -> None:
        '''Called when the artist is updated'''
        pass

    def updated_song_title(self, song_title: str, **kwargs) -> None:
        '''Called when the song title is updated'''
        pass

    async def shutdown(self, message: str, **kwargs) -> None:
        '''Called when a shutdown event is received'''
        self._is_running = False

    @abstractmethod
    async def loop(self) -> None:
        '''Called to start the observer's main loop'''
        pass


