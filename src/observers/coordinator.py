import logging
import asyncio
from .observer_base import ObserverBase, UpdateEventType

class Coordinator:
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger(__class__. __name__)
        self.observers : list[ObserverBase] = []
        self._observer_tasks : dict[ObserverBase, asyncio.Task] = {}
        self._running : bool = True
       

    def add_observer(self, observer: ObserverBase):
        if observer not in self.observers:
            task = asyncio.create_task(observer.loop())
            self._observer_tasks[observer] = task
            self.observers.append(observer)

    def remove_observer(self, observer: ObserverBase):
        if observer in self.observers:
            self.observers.remove(observer)
            if observer in self._observer_tasks:
                task = self._observer_tasks.pop(observer)
                task.cancel()

    def notify_observers(self, update_type: UpdateEventType, value: str, **kwargs):
        for observer in self.observers:
            #print(f"Notifying observer {observer.__class__.__name__} of update type {update_type} with value: {value}")
            observer.UpdateReceived(update_type=update_type, value=value, **kwargs)
    
    async def loop(self) -> None:
        self._running = True
        while self._running:
            await asyncio.sleep(1.0)
        await self.shutdown()
    
    async def shutdown(self, message: str = "Shutting down coordinator"):
        self._running = False
        
        # Cancel all observer tasks
        for observer, task in self._observer_tasks.items():
            await observer.shutdown(message=message)
            if not task.done():
                task.cancel()
        
        # Wait for all tasks to complete
        if self._observer_tasks:
            await asyncio.gather(*self._observer_tasks.values(), return_exceptions=True)
        
        self._observer_tasks.clear()

    def update_song_info(self, artist: str, song_title: str):
        self.notify_observers(update_type=UpdateEventType.ARTIST, value=artist)
        self.notify_observers(update_type=UpdateEventType.SONG_TITLE, value=song_title)