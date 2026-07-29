import json
from dataclasses import dataclass
from typing import Optional


def _reverse_byte_order(hex_id: str) -> str:
    """shairport-sync (via the AirPlay/DAAP metadata it relays) reports a
    track's persistent ID in the opposite byte order from Music.app's own
    JXA persistentID() property for that same track -- confirmed
    empirically during the Pi Zero port bring-up: reversing the byte-pair
    order of one produces exactly the other (e.g. shairport-sync's
    "8FF435762834CAB1" <-> JXA's "B1CA34287635F48F" for the same track).
    Zero-pads to 8 bytes (16 hex digits) first, since shairport-sync's hex
    string can be short a leading zero nibble -- whatever formats it on
    that end doesn't zero-pad (observed: a real track_id of
    "6017692846C2109", only 15 digits)."""
    padded = hex_id.upper().zfill(16)
    byte_pairs = [padded[i:i + 2] for i in range(0, 16, 2)]
    return "".join(reversed(byte_pairs))


@dataclass(frozen=True)
class Track:
    name: str
    index: int
    artist: str
    persistent_id: str


class Playlist:
    def __init__(self, tracks: list[dict]):
        self._by_index: dict[int, Track] = {}
        self._by_persistent_id: dict[str, Track] = {}

        for raw in tracks:
            track = Track(
                name=raw["Name"],
                index=raw["Index"],
                artist=raw["Artist"],
                persistent_id=raw["PersistentID"].upper(),
            )
            self._by_index[track.index] = track
            self._by_persistent_id[track.persistent_id] = track

    @classmethod
    def from_file(cls, path: str) -> "Playlist":
        """Build a Playlist from a JSON file in the same shape
        get_playlist_tracks.js returns (a list of {Name, Index, Artist,
        PersistentID} objects). Not used by the live app -- it fetches the
        playlist from Music.app over SSH instead (see
        MusicAppSSHWorker.get_playlist_tracks() and main.py's
        loadPlaylistFromMac()), since an on-device copy can't be kept in
        sync once the filesystem is read-only. Useful for local dev/testing
        without a Mac reachable over SSH -- point it at your own fixture
        file."""
        with open(path, "r") as f:
            return cls(json.load(f))

    def get_by_index(self, index: int) -> Optional[Track]:
        return self._by_index.get(index)

    def get_by_persistent_id(self, persistent_id: str) -> Optional[Track]:
        return self._by_persistent_id.get(persistent_id.upper())

    def get_by_persistent_id_as_int(self, persistent_id: int) -> Optional[Track]:
        return self.get_by_persistent_id(format(persistent_id, "X"))

    def get_by_shairport_sync_track_id(self, track_id: str) -> Optional[Track]:
        """Looks up a track by the ID string shairport-sync publishes as
        its /track_id MQTT metadata (see §9 of docs/SPECIFICATION.md).
        Not a plain get_by_persistent_id() call -- shairport-sync's ID is
        in the opposite byte order from Music.app's own JXA
        persistentID(), which is what tracks are keyed by here (see
        _reverse_byte_order())."""
        return self.get_by_persistent_id(_reverse_byte_order(track_id))

    def __len__(self) -> int:
        return len(self._by_index)
