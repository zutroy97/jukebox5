from abc import abstractmethod, ABC
import asyncio
from collections.abc import Callable
import logging
import time

class JukeboxPanelInputBase(ABC):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger(self.__class__.__name__)

        if "onButtonPress" not in kwargs:
            raise TypeError("Missing required keyword argument: 'onButtonPress'")
        x = kwargs['onButtonPress']
        # if x is not Callable[[str], None]:
        #     raise TypeError("onButtonPress does not have the proper signature.")
        self._onButtonPress : Callable[[str], None] = x  

    def _buttonPressReceived(self, button_text: str):
        '''Call when a button has been pressed'''
        self._onButtonPress(button_text)

    # @abstractmethod
    # async def loop(self) -> None:
    #     pass

class JukeboxPanelOutputBase(ABC):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def WriteToThreeDigitDisplay(self, message: str):
        '''Write out the string to the 3 digit display'''
        pass

    @abstractmethod
    def ClearThreeDigitDisplay(self):
        '''Clear the 3 digit display'''
        pass

    @abstractmethod
    def WriteToFourDigitDisplay(self, message):
        '''Write out the string to the 3 digit display'''
        pass

    @abstractmethod
    def ClearFourDigitDisplay(self):
        '''Clear the 3 digit display'''
        pass

    @abstractmethod
    def RightLedSet(self, value : bool): 
        '''Turn on or off LED0'''
        pass

    @abstractmethod
    def LeftLedSet(self, value : bool): 
        '''Turn on or off LED0'''
        pass
    
    @abstractmethod
    def Off(self):
        '''Turn off all LEDs'''
        pass
    
    @abstractmethod
    def Clear(self):
        '''Blank all 7 segment LEDs. LED0 and LED1 unaffected'''
        pass


from serial import Serial
from collections import deque
import re
import threading

class JukeboxPanelArduinoSerial(JukeboxPanelInputBase, JukeboxPanelOutputBase):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "port" not in kwargs:
            raise TypeError("Missing required keyword argument: 'port'")
        x = kwargs['port']
        # if x is not Serial:
        #     raise TypeError("port must be a Serial object.")
        self._port : Serial = x  
        self._queueSerialIn = deque([])
        self._patternBTN = re.compile(r"BTN:([0-9]|R|P)", re.A)
        self._inputBuffer = ''
        self.IsRunning : bool = True
        self._threadReadLoop = threading.Thread(target=self._read_from_port_loop)
        self._threadReadLoop.daemon = True
        self._threadReadLoop.start()

    # Write out the string to the 3 digit display
    def WriteToThreeDigitDisplay(self, message : str):
        self._write('w3 ' + message)

    def ClearThreeDigitDisplay(self):
        self.WriteToThreeDigitDisplay('   ')

    # Write out the string to the 4 digit display
    def WriteToFourDigitDisplay(self, message: str):
        self._write('w4 ' + message)

    # Clear the 4 digit display
    def ClearFourDigitDisplay(self):
        self.WriteToFourDigitDisplay('    ')
    
    def _write(self, value):
        self._port.write((value + '\r\n').encode('ascii'))
        self._port.flush()

    # Turn on or off LED0
    def LeftLedSet(self, value): 
        if (value):
            self._write('led1 1')
        else:
            self._write('led1')

    # Turn on or off LED1
    def RightLedSet(self, value):
        if (value):
            self._write('led0 1')
        else:
            self._write('led0')
    
    # Turn off all LEDs
    def Off(self):
        self._write('off')
    
    # Blank all 7 segment LEDs. LED0 and LED1 unaffected
    def Clear(self):
        self._write('c')

    def _read_from_port_loop(self):
        while self.IsRunning:
            c = self._port.read(size=1) # Attempt to read a character. Blocks based on timeout set on Serial object __init__
            if (len(c) > 0):
                #print("GOT CHAR! {0}".format(c))
                self._inputBuffer = (self._inputBuffer + (c.decode('ascii'))).replace(">\n", '') # Filter out the > prompt.
                parts =  self._inputBuffer.split("\n")  # Each response from arduino ends with \n. Split them all up into a list.
                if len(self._inputBuffer) > 10:
                    # Safety valve. No single respnose should be over 50 characters.
                    logging.warning("JukeboxPanelSerialDriver: inputBuffer > 50 {0} {1}".format(len(self._inputBuffer), self._inputBuffer))                
                    self._inputBuffer = '' # Reset the input buffer in emegency
                if len(parts) > 1:
                    # At least one new line (& response) was detected
                    self._queueSerialIn.extendleft(parts[:-1]) # Add all parts except the last (incomplete) one
                    self._inputBuffer = parts[-1] # Reset the buffer to the last (incomplete) response.
                    while len(self._queueSerialIn) > 0: # While there are responses in the queue, process them.
                        raw = self._queueSerialIn.pop() # Get the earliest response
                        m = self._patternBTN.search(raw)    # Does this match a button pressed response?
                        if m:
                            self._buttonPressReceived(m.group(1))   # call it with the button.
            else:
                time.sleep(0.01)
