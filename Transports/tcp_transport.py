from .transport_base import Transport
from Utils import Config

class TCPTransport(Transport):
    def __init__(self, session):
        super().__init__(session)
        self.conn = self.session.wconn
        self.track_map = {}
        self.socks = {}

    def conf_track(self, track):
        """Set target port for tracks"""
        if track.track_id in self.track_map:
            p = Config().get_free_port("relay")
            Config().port_set_used(p)
            track.ffmpeg_target_port = p

    def on_play(self):
        pass

    def on_traffic(self, data, track_id, relay_id):
        """Decide on channel and re-send data to client"""
        channel = self.track_map[track_id][relay_id]
        # parse the RTP sequence number from the packet header
        header = bytes([36, channel]) + len(data).to_bytes(2, 'big')
        self.conn.send(header + data)


    def on_pause(self):
        pass