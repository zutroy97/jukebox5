import os
import re
import threading

from panel.panel_input_base import JukeboxPanelInputBase, JukeboxPanelOutputBase


class JukeboxPanelLinuxAsciiModule(JukeboxPanelInputBase, JukeboxPanelOutputBase):
    """Talks to the jukebox_panel Linux kernel driver over /dev/jukebox_panel
    using its line-based text protocol ("w3 <text>\\n", "BTN:<c>\\n", ...) --
    the same proven protocol JukeboxPanelArduinoSerial speaks over a serial
    port, just over the character device file instead. See
    linux/jukeboxPanelModule/WIRING.md for the wire-level command list.
    """

    READ_CHUNK = 64

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "device" not in kwargs:
            raise TypeError("Missing required keyword argument: 'device'")
        self._device_path = kwargs['device']
        self._fd = os.open(self._device_path, os.O_RDWR)

        self._patternBTN = re.compile(r"BTN:([0-9]|R|P)", re.A)
        self._inputBuffer = ''
        self.IsRunning: bool = True
        self._threadReadLoop = threading.Thread(target=self._read_loop, daemon=True)
        self._threadReadLoop.start()

    def close(self):
        self.IsRunning = False
        os.close(self._fd)

    # --- JukeboxPanelOutputBase ---

    def WriteToThreeDigitDisplay(self, message: str, animated: bool = True):
        self._write('w3 ' + message)

    def WriteNumberToThreeDigitDisplay(self, num: int):
        self._write('w3 ' + str(num).rjust(3))

    def ClearThreeDigitDisplay(self):
        self.WriteToThreeDigitDisplay('   ')

    def WriteToFourDigitDisplay(self, message: str, animated: bool = True):
        self._write('w4 ' + message)

    def WriteNumberToFourDigitDisplay(self, num: int):
        self._write('w4 ' + str(num).rjust(4))

    def ClearFourDigitDisplay(self):
        self.WriteToFourDigitDisplay('    ')

    def LeftLedSet(self, value: bool):
        self._write('led1 1' if value else 'led1')

    def RightLedSet(self, value: bool):
        self._write('led0 1' if value else 'led0')

    def Off(self):
        self._write('off')

    def Clear(self):
        self._write('c')

    # --- internals ---

    def _write(self, value: str):
        os.write(self._fd, (value + '\n').encode('ascii'))

    def _read_loop(self):
        while self.IsRunning:
            try:
                chunk = os.read(self._fd, self.READ_CHUNK)
            except OSError:
                if not self.IsRunning:
                    return
                raise

            if not chunk:
                continue

            self._inputBuffer += chunk.decode('ascii', errors='replace')
            parts = self._inputBuffer.split('\n')
            self._inputBuffer = parts[-1]
            for line in parts[:-1]:
                m = self._patternBTN.search(line)
                if m:
                    self._buttonPressReceived(m.group(1))
