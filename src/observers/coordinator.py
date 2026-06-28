import logging
import threading

from panel.panel_input_base import JukeboxPanelInputBase, JukeboxPanelOutputBase
from .observer_base import ObserverBase, UpdateEventType
import time

class Coordinator:
    TimeoutLimitInSeconds : int = 30 * 60
    def __init__(self, **kwargs) -> None:
        #super().__init__()
        self._logger = logging.getLogger(__class__. __name__)
        self.observers : list[ObserverBase] = []
        self.IsRunning : bool = True
        self._timeout : float = -1.0
        self._panelButton : JukeboxPanelInputBase = kwargs['panelButtons']
        self._panelDisplay : JukeboxPanelOutputBase = kwargs['panelDisplay']
        self._updateCount : int = 0
        self._reset_timeout()
        self.updateJukeboxDisplay()

        self._threadReadLoop = threading.Thread(target=self.loop)
        self._threadReadLoop.daemon = True
        self._threadReadLoop.start()        

    def add_observer(self, observer: ObserverBase):
        if observer not in self.observers:
            self.observers.append(observer)

    def remove_observer(self, observer: ObserverBase):
        if observer in self.observers:
            self.observers.remove(observer)

    def notify_observers(self, update_type: UpdateEventType, value: str, **kwargs):
        self._reset_timeout()
        for observer in self.observers:
            #print(f"Notifying observer {observer.__class__.__name__} of update type {update_type} with value: {value}")
            observer.UpdateReceived(update_type=update_type, value=value, **kwargs)
    
    def loop(self) -> None:
        while self.IsRunning:
            is_timeout = self._timeout > 0 and time.monotonic() >= self._timeout
            if is_timeout:
                self.notify_observers(UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT, '')
                self._timeout = -1.0 # disable trigger
            for observer in self.observers:
                observer.draw()
            time.sleep(0.033)
    
    def shutdown(self, message: str = "Shutting down coordinator"):
        self.IsRunning = False
        for observer in self.observers:
            observer.shutdown(message=message)

    def update_song_info(self, artist: str, song_title: str):
        self.notify_observers(update_type=UpdateEventType.ARTIST, value=artist)
        self.notify_observers(update_type=UpdateEventType.SONG_TITLE, value=song_title)
        self._updateCount += 1
        self.updateJukeboxDisplay()

    def _reset_timeout(self):
        self._timeout = time.monotonic() + Coordinator.TimeoutLimitInSeconds

    def updateJukeboxDisplay(self):
        x = self._updateCount % 2
        self._panelDisplay.LeftLedSet(x == 1)
        self._panelDisplay.RightLedSet(x == 0)
        self._panelDisplay.WriteToThreeDigitDisplay(str(self._updateCount))