from ..observer_base import UpdateEventType, ObserverBase
from .single_text_line_animated import SingleTextLineAnimatedObserver
from observers.observer_states import ObserverStates

class KeyValueTextObserver(ObserverBase):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        if "key_driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'key_driver'")
        self._key_driver : SingleTextLineAnimatedObserver = kwargs['key_driver']
        self._key_driver.auto_loop = False

        if "value_driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'value_driver'")
        self._value_driver : SingleTextLineAnimatedObserver = kwargs['value_driver'] 
        self._value_driver.auto_loop = False

        self._db : dict[str, str] = {}
        self._display_keys = []

    async def draw(self) -> None:
        '''Called to draw the current state of the observer. Should be implemented by subclasses.'''
        if len(self._display_keys) == 0:
            self._display_keys = list(self._db.keys())
            # await self._key_driver.clear_display()
            # await self._value_driver.clear_display()
        elif self._key_driver._state in [ObserverStates.ANIMATION_FINISHED, ObserverStates.IDLE] and self._value_driver._state in [ObserverStates.ANIMATION_FINISHED, ObserverStates.IDLE]:
            # time to update the displays
            key = self._display_keys.pop()
            self._key_driver.Value = key
            self._value_driver.Value = self._db[key]
        await self._key_driver.draw()
        await self._value_driver.draw()

    def updated_artist(self, artist: str, **kwargs) -> None:
        self._db["Artist"] = artist

    def updated_song_title(self, song_title: str, **kwargs) -> None:
        # self._key_driver.Value = "Title"
        # self._value_driver.Value = song_title
        self._db["Title"] = song_title 
