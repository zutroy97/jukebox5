// Direct "skip to previous track" for the macOS "Music" app, run as
// JavaScript for Automation (JXA) over SSH by
// MusicAppSSHWorker.previous_track(). See playpause.js for why this talks
// to the Music app directly instead of going through shairport-sync's
// MQTT/DACP remote-control path.
(() => {
  const Music = Application("Music");
  try {
    Music.previousTrack();
  } catch (e) {
    return "previousTrack failed: " + e;
  }
  return "OK";
})();
