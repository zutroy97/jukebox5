
import asyncio

from .observer_base import UpdateEventType, ObserverBase
from drivers import abstract_line_display


class SingleLineObserver(ObserverBase):

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._driver : abstract_line_display = kwargs.get('driver', None)
        self._event_type : UpdateEventType = kwargs.get('event_type', None)
        self._text : str = ""
        self._textUpdateNeeded : bool = False


    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        '''Called when an update is received'''
        if self._event_type is None or update_type != self._event_type:
            return
    
        value = kwargs.get('value', self._text)
        if value != self._text:
            self._text = value
            self._textUpdateNeeded = True

    async def loop(self) -> None:
        '''Called to start the observer's main loop'''
        self._is_running = True
        while self._is_running:
            if self._textUpdateNeeded and self._driver is not None:
                await self._driver.clear()
                await self._driver.write(self._text)
                self._textUpdateNeeded = False
            await asyncio.sleep(0.1)  # Simulate some work
