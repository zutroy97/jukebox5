
from .observer_base import UpdateEventType, ObserverBase
from time import gmtime, strftime


class TerminalObserver(ObserverBase):

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def updated_artist(self, artist: str, **kwargs) -> None:
        print(f"{strftime('%H:%M:%S', gmtime())} Artist: {artist}")

    def updated_song_title(self, song_title: str, **kwargs) -> None:
        print(f"{strftime('%H:%M:%S', gmtime())} Song title: {song_title}")

    def updated_shutdown(self, message: str, **kwargs) -> None:
        print(f"{strftime('%H:%M:%S', gmtime())} Shutdown message received: {message}")


