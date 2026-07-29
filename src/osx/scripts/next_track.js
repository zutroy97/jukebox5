// Direct "skip to next track" for the macOS "Music" app, run as
// JavaScript for Automation (JXA) over SSH by
// MusicAppSSHWorker.next_track(). See playpause.js for why this talks to
// the Music app directly instead of going through shairport-sync's MQTT/
// DACP remote-control path.
(() => {
  const Music = Application("Music");
  try {
    Music.nextTrack();
  } catch (e) {
    return "nextTrack failed: " + e;
  }
  return "OK";
})();
