from abc import ABC, abstractmethod

class AbstractSingleLineDisplay(ABC):
    @abstractmethod
    def clear(self):
        '''Clear the display.'''
        pass

    @abstractmethod
    def write(self, text: str):
        '''Write text to the display.'''
        pass

    @abstractmethod
    def set_position(self, position: int):
        '''Set the cursor position on the display.'''
        pass

    @property
    @abstractmethod
    def Width(self) -> int:
        '''Get the width of the display.'''
        pass

    def write_at_position(self, position: int, text: str ):
        '''Write text to the display at a specific position.'''
        self.set_position(position)
        self.write(text)