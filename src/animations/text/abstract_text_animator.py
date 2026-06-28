from abc import abstractmethod

from ..abstract_animator import AbstractAnimator

class AbstractTextAnimator(AbstractAnimator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    @abstractmethod
    def Start(self) -> None:
        '''Initializes the animation using the existing text. Must be called before any other methods.'''
        pass

    def StartWithText(self, new_text: str) -> None:
        '''Initializes the animation using the new_text.'''
        self._text = new_text[:self.max_text_width] # truncate text to max width if necessary
        self.Start()

    @abstractmethod
    def GetText(self) -> str:
        '''Returns the text to be displayed'''
        return ""
    

    


        