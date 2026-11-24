# hypnomix patch: negative track ids reach the master and return tracks.
#   -1 = master, -2 = return A, -3 = return B, ...
def resolve_track(song, index):
    index = int(index)
    if index >= 0:
        return song.tracks[index]
    if index == -1:
        return song.master_track
    return song.return_tracks[-index - 2]
