from abc import ABC, abstractmethod

class AbstractSingleLineDisplay(ABC):
    @abstractmethod
    async def clear(self):
        '''Clear the display.'''
        pass

    @abstractmethod
    async def write(self, text: str):
        '''Write text to the display.'''
        pass

    @abstractmethod
    async def set_position(self, position: int):
        '''Set the cursor position on the display.'''
        pass

    @property
    @abstractmethod
    def Width(self) -> int:
        '''Get the width of the display.'''
        pass

    async def write_at_position(self, text: str, position: int):
        '''Write text to the display at a specific position.'''
        await self.set_position(position)
        await self.write(text)