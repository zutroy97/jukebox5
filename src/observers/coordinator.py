import logging
import asyncio
from .observer_base import ObserverBase, UpdateEventType

class Coordinator:
    def __init__(self, **kwargs) -> None:
        #super().__init__()
        self._logger = logging.getLogger(__class__. __name__)
        self.observers : list[ObserverBase] = []
        self._running : bool = True
       

    def add_observer(self, observer: ObserverBase):
        if observer not in self.observers:
            self.observers.append(observer)

    def remove_observer(self, observer: ObserverBase):
        if observer in self.observers:
            self.observers.remove(observer)

    def notify_observers(self, update_type: UpdateEventType, value: str, **kwargs):
        for observer in self.observers:
            #print(f"Notifying observer {observer.__class__.__name__} of update type {update_type} with value: {value}")
            observer.UpdateReceived(update_type=update_type, value=value, **kwargs)
    
    async def loop(self) -> None:
        self._running = True
        while self._running:
            for observer in self.observers:
                await observer.draw()
            await asyncio.sleep(0.001)
    
    async def shutdown(self, message: str = "Shutting down coordinator"):
        self._running = False
        for observer in self.observers:
            await observer.shutdown(message=message)

    def update_song_info(self, artist: str, song_title: str):
        self.notify_observers(update_type=UpdateEventType.ARTIST, value=artist)
        self.notify_observers(update_type=UpdateEventType.SONG_TITLE, value=song_title)