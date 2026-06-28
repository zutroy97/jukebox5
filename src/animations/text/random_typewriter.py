import random
import asyncio
from .abstract_text_animator import AbstractTextAnimator

class RandomTypeWriter(AbstractTextAnimator):
    def __init__(self,  **kwargs) -> None:
        super().__init__(**kwargs)
        self._character_queue = []
        self._frameBuffer : list[str] = []
        
    def Start(self) -> None:
        self._text = self.text[:self.max_text_width] # truncate text to max width if necessary
        self._character_queue = list(range(0, len(self.text)))
        random.shuffle(self._character_queue)
        self._frameBuffer = list(' ' * len(self.text)) # empty string of the same length as text, to be filled in as the animation progresses   

    def Next(self) -> bool:
        '''Returns true if more data is available'''
        return len(self._character_queue) > 0

    def GetText(self) -> str:
        '''Returns the text to be displayed'''
        x = self._character_queue.pop(0)
        self._frameBuffer[x] = self.text[x]
        return ''.join(self._frameBuffer).ljust(self.max_text_width)
