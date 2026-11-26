from gamedb.explorer.disc_audio import cue_audio_tracks


def test_only_split_audio_tracks_are_exposed_and_index_01_skips_the_pregap():
    cue = b'''
FILE "data.bin" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
FILE "music.bin" BINARY
  TRACK 02 AUDIO
    INDEX 00 00:00:00
    INDEX 01 00:02:00
FILE "joined.bin" BINARY
  TRACK 03 AUDIO
    INDEX 01 00:00:00
  TRACK 04 AUDIO
    INDEX 01 01:00:00
'''
    files = [{"memberPath": name, "size": 2352 * 300, "sha1": "a" * 40}
             for name in ("data.bin", "music.bin", "joined.bin")]

    assert cue_audio_tracks(cue, files) == {"02": ("music.bin", 2352 * 300, "a" * 40, 2352 * 150)}
