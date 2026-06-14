from abc import abstractmethod, ABC
import logging

class AbstractAnimator(ABC):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger()
        self._text = kwargs.get('text', '')
#        self._done : bool = False
        self._max_text_width = kwargs.get('max_text_width', 20)

    @property
    def max_text_width(self) -> int:
        return self._max_text_width
    
    @max_text_width.setter
    def max_text_width(self, value: int) -> None:
        self._max_text_width = value
    
    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        self._text = value
    
    @abstractmethod
    async def Next(self) -> bool:
        '''Returns true if more data is available'''
        return False
    
    @abstractmethod
    async def Start(self) -> None:
        '''Start/Restarts the animation'''
        pass    
       