from abc import abstractmethod, ABC
from collections.abc import Callable
import logging
import time

class JukeboxPanelInputBase(ABC):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        if "onButtonPress" not in kwargs:
            raise TypeError("Missing required keyword argument: 'onButtonPress'")
        self._onButtonPress: Callable[[str], None] = kwargs['onButtonPress']

    def _buttonPressReceived(self, button_text: str):
        self._onButtonPress(button_text)


class JukeboxPanelOutputBase(ABC):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def WriteToThreeDigitDisplay(self, message: str): pass

    @abstractmethod
    def WriteNumberToThreeDigitDisplay(self, num: int): pass    

    @abstractmethod
    def WriteNumberToFourDigitDisplay(self, num: int): pass    

    @abstractmethod
    def ClearThreeDigitDisplay(self): pass

    @abstractmethod
    def WriteToFourDigitDisplay(self, message): pass

    @abstractmethod
    def ClearFourDigitDisplay(self): pass

    @abstractmethod
    def RightLedSet(self, value: bool): pass

    @abstractmethod
    def LeftLedSet(self, value: bool): pass

    @abstractmethod
    def Off(self): pass

    @abstractmethod
    def Clear(self): pass


from serial import Serial
from collections import deque
import os
import re
import select
import threading


class JukeboxPanelArduinoSerial(JukeboxPanelInputBase, JukeboxPanelOutputBase):
    # How long read() blocks waiting for a byte before looping.
    # Large enough to avoid spinning; small enough to notice IsRunning=False promptly.
    READ_TIMEOUT_S: float = 0.5

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "port" not in kwargs:
            raise TypeError("Missing required keyword argument: 'port'")
        self._port: Serial = kwargs['port']

        # Ensure the serial port uses a read timeout so _read_from_port_loop
        # blocks in the kernel rather than spinning on empty reads.
        if self._port.timeout != self.READ_TIMEOUT_S:
            self._port.timeout = self.READ_TIMEOUT_S

        self._queueSerialIn = deque([])
        self._patternBTN = re.compile(r"BTN:([0-9]|R|P)", re.A)
        self._inputBuffer = ''
        self.IsRunning: bool = True
        self._threadReadLoop = threading.Thread(target=self._read_from_port_loop, daemon=True)
        self._threadReadLoop.start()

    def WriteToThreeDigitDisplay(self, message: str):
        self._write('w3 ' + message)

    def WriteNumberToThreeDigitDisplay(self, num: int):
        self._write('w3 ' + str(num).rjust(3))        

    def ClearThreeDigitDisplay(self):
        self.WriteToThreeDigitDisplay('   ')

    def WriteToFourDigitDisplay(self, message: str):
        self._write('w4 ' + message)

    def WriteNumberToFourDigitDisplay(self, num: int):
        self._write('w4 ' + str(num).rjust(4))

    def ClearFourDigitDisplay(self):
        self.WriteToFourDigitDisplay('    ')

    def _write(self, value: str):
        self._port.write((value + '\r\n').encode('ascii'))
        self._port.flush()

    def LeftLedSet(self, value: bool):
        self._write('led1 1' if value else 'led1')

    def RightLedSet(self, value: bool):
        self._write('led0 1' if value else 'led0')

    def Off(self):
        self._write('off')

    def Clear(self):
        self._write('c')

    def _read_from_port_loop(self):
        while self.IsRunning:
            # read() blocks for up to READ_TIMEOUT_S then returns b'' — no sleep() needed.
            c = self._port.read(size=1)
            if not c:
                continue  # timeout expired with no data; loop and block again

            self._inputBuffer = (
                self._inputBuffer + c.decode('ascii')
            ).replace(">\n", '')

            if len(self._inputBuffer) > 50:
                logging.warning(
                    "JukeboxPanelSerialDriver: inputBuffer overflow (%d): %r",
                    len(self._inputBuffer), self._inputBuffer
                )
                self._inputBuffer = ''
                continue

            parts = self._inputBuffer.split('\n')
            if len(parts) > 1:
                self._queueSerialIn.extendleft(parts[:-1])
                self._inputBuffer = parts[-1]
                while self._queueSerialIn:
                    raw = self._queueSerialIn.pop()
                    m = self._patternBTN.search(raw)
                    if m:
                        self._buttonPressReceived(m.group(1))


class JukeboxPanelGPIODevice(JukeboxPanelInputBase, JukeboxPanelOutputBase):
    """Talks to the jukeboxPanelModule Linux kernel driver over a character
    device (default /dev/jukebox_panel), replacing the Arduino + serial link.

    Speaks the exact same line-based text protocol as JukeboxPanelArduinoSerial
    (see jukeboxPanelModule/jukebox_panel.c) -- only the transport differs, so
    the read-loop/command logic below closely mirrors that class's.
    """

    # How long select() blocks waiting for readable data before looping.
    # Large enough to avoid spinning; small enough to notice IsRunning=False promptly.
    READ_TIMEOUT_S: float = 0.5

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "device" not in kwargs:
            raise TypeError("Missing required keyword argument: 'device'")
        self._fd = os.open(kwargs['device'], os.O_RDWR | os.O_NONBLOCK)

        self._queueSerialIn = deque([])
        self._patternBTN = re.compile(r"BTN:([0-9]|R|P)", re.A)
        self._inputBuffer = ''
        self.IsRunning: bool = True
        self._threadReadLoop = threading.Thread(target=self._read_from_device_loop, daemon=True)
        self._threadReadLoop.start()

    def WriteToThreeDigitDisplay(self, message: str):
        self._write('w3 ' + message)

    def WriteNumberToThreeDigitDisplay(self, num: int):
        self._write('w3 ' + str(num).rjust(3))

    def ClearThreeDigitDisplay(self):
        self.WriteToThreeDigitDisplay('   ')

    def WriteToFourDigitDisplay(self, message: str):
        self._write('w4 ' + message)

    def WriteNumberToFourDigitDisplay(self, num: int):
        self._write('w4 ' + str(num).rjust(4))

    def ClearFourDigitDisplay(self):
        self.WriteToFourDigitDisplay('    ')

    def _write(self, value: str):
        os.write(self._fd, (value + '\r\n').encode('ascii'))

    def LeftLedSet(self, value: bool):
        self._write('led1 1' if value else 'led1')

    def RightLedSet(self, value: bool):
        self._write('led0 1' if value else 'led0')

    def Off(self):
        self._write('off')

    def Clear(self):
        self._write('c')

    def _read_from_device_loop(self):
        while self.IsRunning:
            # select() blocks for up to READ_TIMEOUT_S then returns empty -- no sleep() needed.
            ready, _, _ = select.select([self._fd], [], [], self.READ_TIMEOUT_S)
            if not ready:
                continue  # timeout expired with no data; loop and block again

            c = os.read(self._fd, 64)
            if not c:
                continue

            self._inputBuffer = self._inputBuffer + c.decode('ascii')

            if len(self._inputBuffer) > 50:
                logging.warning(
                    "JukeboxPanelGPIODevice: inputBuffer overflow (%d): %r",
                    len(self._inputBuffer), self._inputBuffer
                )
                self._inputBuffer = ''
                continue

            parts = self._inputBuffer.split('\n')
            if len(parts) > 1:
                self._queueSerialIn.extendleft(parts[:-1])
                self._inputBuffer = parts[-1]
                while self._queueSerialIn:
                    raw = self._queueSerialIn.pop()
                    m = self._patternBTN.search(raw)
                    if m:
                        self._buttonPressReceived(m.group(1))