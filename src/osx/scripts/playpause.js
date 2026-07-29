// Direct playback toggle for the macOS "Music" app, run as JavaScript for
// Automation (JXA) over SSH by MusicAppSSHWorker.playpause().
//
// Replaces shairport-sync's own MQTT/DACP remote-control path for this
// command: DACP's remote control has no acknowledgment of whether a
// command actually took effect (see ShairportSyncMQTTSource.
// send_remote_command()'s docstring), and was observed silently failing
// during the Pi Zero port bring-up even with a live AirPlay session.
// Talking to the Music app directly over the already-open SSH connection
// gives a real exit status instead.
//
// Left as a plain top-level IIFE (no `function run(argv)`) for the same
// reason as recover_airplay_playback.js -- piped into osascript's stdin
// rather than invoked with arguments.
(() => {
  const Music = Application("Music");
  try {
    Music.playpause();
  } catch (e) {
    return "playpause failed: " + e;
  }
  return "OK";
})();
