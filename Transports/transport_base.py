class Transport:
    def __init__(self, session):
        self.session = session

    def conf_track(self, track):
        """Configure track for further playback"""
        raise NotImplementedError("conf_track not implemented")

    def on_play(self):
        """Prepare for playback"""
        raise NotImplementedError("on_play not implemented")

    def on_traffic(self, data, track_id, relay_id):
        """Re-pack and send data to client"""
        raise NotImplementedError("on_traffic not implemented")

    def on_pause(self):
        """Cleanup for the next playback"""
        raise NotImplementedError("on_pause not implemented")

    def on_teardown(self):
        """Final cleanup"""
        pass
