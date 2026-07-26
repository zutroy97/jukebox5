from abc import abstractmethod, ABC
import logging

class AbstractAnimator(ABC):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger()
        self._text = kwargs.get('text', '')
#        self._done : bool = False
        self._max_text_width = kwargs.get('max_text_width', 20)
        # Parallel to self._text -- dp_flags[i] is True if text[i]'s cell
        # should also light its decimal-point segment (see
        # animations.text.period_fold.fold_periods, which is what actually
        # produces these). Defaults to all-False so callers that never
        # pass dp_flags (i.e. don't care about the feature) are unaffected.
        self._dp_flags: list[bool] = kwargs.get('dp_flags') or [False] * len(self._text)

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

    @property
    def dp_flags(self) -> list[bool]:
        return self._dp_flags

    @dp_flags.setter
    def dp_flags(self, value: list[bool]) -> None:
        self._dp_flags = value

    @abstractmethod
    def Next(self) -> bool:
        '''Returns true if more data is available'''
        return False
    
    @abstractmethod
    def Start(self) -> None:
        '''Start/Restarts the animation'''
        pass    
       