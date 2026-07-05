from ..observer_base import UpdateEventType, ObserverBase
from drivers.abstract_line_display import AbstractSingleLineDisplay

class SingleTextLineStaticObserver(ObserverBase):

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'driver'")
        self._driver : AbstractSingleLineDisplay = kwargs['driver']
       
        if "event_type" not in kwargs:
            raise TypeError("Missing required keyword argument: 'event_type'")
        self._event_type : UpdateEventType = kwargs['event_type']

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

    def draw(self) -> None:
        '''Called to start the observer's main loop'''
        if self._textUpdateNeeded and self._driver is not None:
            self._driver.clear()
            self._driver.write(self._text)
            self._textUpdateNeeded = False

