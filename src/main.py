import time
import threading
import logging

import drivers as ldisp
from animations import RandomTypeWriter
from animations.abstract_clear_animator import ClearTextBlankLeftToRightAnimator
from observers import UpdateEventType, Coordinator, SingleTextLineAnimatedObserver, KeyValueTextObserver
from panel.panel_input_base import JukeboxPanelArduinoSerial
from shairport_mqtt import ShairportSyncMQTTSource

from serial import Serial


led0 = ldisp.led16_display(addr=(0x70, 0x71))
led1 = ldisp.led16_display(addr=(0x72, 0x73, 0x74))


def onPanelButtonPress(key: str):
    print(f"Button Pressed: {key}")


def exercise(coordinator: Coordinator):
    '''Manual test harness: feeds a fake playlist through the coordinator so
    the display rotation can be exercised without a live shairport-sync/MQTT
    connection.'''
    sleep_s: int = 20
    coordinator.update_song_info(artist="Chumbawamba", song_title="Tubthumping (I Get Knocked Down)")
    time.sleep(sleep_s)

    coordinator.update_song_info(artist="Conway Twitty", song_title="Hello Darlin'")
    time.sleep(sleep_s)

    coordinator.update_song_info(artist="Kiss", song_title="I Was Made For Lovin' You")
    time.sleep(sleep_s)

    coordinator.update_song_info(artist="Johnny Cash & June Carter", song_title="Jackson")
    time.sleep(sleep_s)
    coordinator.update_song_info(artist="John Williams", song_title="Jurassic Park Theme")
    time.sleep(sleep_s)
    coordinator.update_song_info(artist="Nirvana", song_title="Smells Like Teen Spirit")
    time.sleep(sleep_s)
    coordinator.update_song_info(artist="Weird Al Yankovic", song_title="Amish Paradise")
    time.sleep(sleep_s)

    coordinator.shutdown()


def main():
    panelSerial = Serial(port='/dev/cu.usbserial-3220', baudrate=115200, timeout=None)
    panel = JukeboxPanelArduinoSerial(port=panelSerial, onButtonPress=onPanelButtonPress)
    coordinator = Coordinator(panelButtons=panel, panelDisplay=panel)

    led_artist_observer = SingleTextLineAnimatedObserver(driver=led0, event_type=UpdateEventType.ARTIST)
    led_artist_observer.delay_after_animation_finished_s = 2

    led_song_title_observer = SingleTextLineAnimatedObserver(driver=led1, event_type=UpdateEventType.SONG_TITLE)
    led_song_title_observer.delay_after_animation_finished_s = 2
    led_song_title_observer.changeAnimation(RandomTypeWriter())
    led_song_title_observer.ClearDisplayAnimation = ClearTextBlankLeftToRightAnimator()

    kv_observer = KeyValueTextObserver(key_driver=led_artist_observer, value_driver=led_song_title_observer)
    coordinator.add_observer(kv_observer)

    # exercise(coordinator)
    source = ShairportSyncMQTTSource(
        on_song_changed=coordinator.update_song_info,
        on_play_end=coordinator.play_ended,
        broker_host="jukebox4",   # or your broker's IP
        base_topic="shairport-sync",
    )
    source.start()

    coordinator.add_message("Weather", "Sunny 72°F", ttl_s=300, display_s=5)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        source.stop()
        coordinator.shutdown()


if __name__ == '__main__':
    formatter = logging.Formatter(
        fmt='%(asctime)s.%(msecs)03d %(name)s %(levelname)s %(message)s',
        datefmt='%M:%S'
    )
    logger = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    main()
