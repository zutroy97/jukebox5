from abc import abstractmethod

from ..abstract_animator import AbstractAnimator

class AbstractTextAnimator(AbstractAnimator):
    def __init__(self, **kwargs) -> None:
        super().__init__()

    @abstractmethod
    async def GetText(self) -> str:
        '''Returns the text to be displayed'''
        return ""
    

    


        