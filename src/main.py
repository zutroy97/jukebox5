import time

import drivers as ldisp
import threading
import logging
from animations import RandomTypeWriter, Slide
from observers import UpdateEventType, Coordinator,  SingleTextLineAnimatedObserver,KeyValueTextObserver, SingleLineLed16AnimatedObserver
from animations.abstract_clear_animator import AbstractClearTextAnimator, ClearTextImmediatelyAnimator, ClearTextBlankLeftToRightAnimator

from serial import Serial
from panel.panel_input_base import JukeboxPanelArduinoSerial, JukeboxPanelOutputBase
from shairport_mqtt import ShairportSyncMQTTSource


led0 = ldisp.led16_display(addr=(0x70, 0x71))
led1 = ldisp.led16_display(addr=(0x72, 0x73, 0x74))

def onPanelButtonPress(key : str):
    print(f"Button Pressed: {key}")

def exercise(coorinator: Coordinator):
    sleep_s : int = 20
    coorinator.update_song_info(artist="Chumbawamba", song_title="Tubthumping (I Get Knocked Down)")
    time.sleep(sleep_s)   
    
    coorinator.update_song_info(artist="Conway Twitty", song_title="Hello Darlin'")
    time.sleep(sleep_s)

    coorinator.update_song_info(artist="Kiss", song_title="I Was Made For Lovin' You")
    time.sleep(sleep_s)

    coorinator.update_song_info(artist="Johnny Cash & June Carter", song_title="Jackson")
    time.sleep(sleep_s)
    coorinator.update_song_info(artist="John Williams", song_title="Jurassic Park Theme")
    time.sleep(sleep_s)
    coorinator.update_song_info(artist="Nirvana", song_title="Smells Like Teen Spirit")
    time.sleep(sleep_s)
    coorinator.update_song_info(artist="Weird Al Yankovic", song_title="Amish Paradise")
    time.sleep(sleep_s)

    coorinator.shutdown()


def main():
    panelSerial = Serial(port='/dev/cu.usbserial-3220', baudrate=115200, timeout=None)
    panel = JukeboxPanelArduinoSerial(port=panelSerial, onButtonPress=onPanelButtonPress)
    #asyncio.create_task(panelButton.loop())
    coorinator = Coordinator(panelButtons= panel, panelDisplay=panel)

    led_artist_observer = SingleTextLineAnimatedObserver(driver=led0, event_type=UpdateEventType.ARTIST)
    led_artist_observer.delay_after_animation_finished_s = 2
 
    led_song_title_observer = SingleTextLineAnimatedObserver(driver=led1, event_type=UpdateEventType.SONG_TITLE)    
    led_song_title_observer.delay_after_animation_finished_s = 2
    led_song_title_observer.changeAnimation(RandomTypeWriter())
    led_song_title_observer.ClearDisplayAnimation = ClearTextBlankLeftToRightAnimator()

    kv_observer = KeyValueTextObserver(key_driver = led_artist_observer, value_driver=led_song_title_observer)
    coorinator.add_observer(kv_observer)

    #exercise(coorinator)
    source = ShairportSyncMQTTSource(
        on_song_changed=coorinator.update_song_info,
        on_play_end=coorinator.play_ended,
        broker_host="jukebox4",   # or your broker's IP
        base_topic="shairport-sync",
    )
    source.start()

    #coorinator.add_message("Weather", "Sunny 72°F", ttl_s=300, display_s=5)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        source.stop()
        coorinator.shutdown()
  

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

# if __name__ == "__main__":
#     import asyncio
#     from animations.text.random_typewriter import RandomTypeWriter
#     from animations.led_16.led16_static import LED16TextAnimatorAdapter

#     async def main():
#         animator = LED16TextAnimatorAdapter(RandomTypeWriter(text="Hello World!", max_text_width=8))
#         await animator.Start()
#         while await animator.Next():
#             #led0._display. set_segments(await animator.GetSegments())  # Update the LED display with the current segments
#             segments = await animator.GetSegments()
#             #print(segments)
#             for i, seg in enumerate(segments):
#                 print(f"Position {i}: {bin(seg)}")
#                 led0._display.set_digit_raw(i, seg)  # Update the LED display with the current segments
#             time.sleep(0.1)  # Add a small delay to control the animation speed
    
#     asyncio.run(main())    

# if __name__ == "__main__":
#     import asyncio
#     from animations.text.random_typewriter import RandomTypeWriter
#     from animations.led_16.led16_static import LED16Static

#     async def main():
#         animator = LED16Static(text="Hello World!", max_text_width=led1.Width)
#         await animator.Start()
#         while await animator.Next():
#             #led0._display. set_segments(await animator.GetSegments())  # Update the LED display with the current segments
#             segments = await animator.GetSegments()
#             #print(segments)
#             for i, seg in enumerate(segments):
#                 print(f"Position {i}: {bin(seg)}")
#                 led1._display.set_digit_raw(i, seg)  # Update the LED display with the current segments
#             time.sleep(0.1)  # Add a small delay to control the animation speed
    
#     asyncio.run(main())    