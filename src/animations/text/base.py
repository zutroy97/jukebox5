from enum import Enum
from abc import abstractmethod, ABC
import logging

class TextAnimatorBase(ABC):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger()
        self._text = kwargs.get('text', '')
        self._done : bool = False
        self._max_text_width = kwargs.get('max_text_width', 20)

    @property
    def max_text_width(self) -> int:
        return self._max_text_width
    
    @property
    def text(self) -> str:
        return self._text

    @abstractmethod
    async def GetText(self) -> str:
        '''Returns the text to be displayed'''
        return ""
    
    @abstractmethod
    async def Next(self) -> bool:
        '''Returns true if more data is available'''
        return False
    
    @abstractmethod
    async def Start(self) -> None:
        '''Start/Restarts the animation'''
        pass
    
