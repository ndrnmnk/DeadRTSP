from .transport_base import Transport
import socket

class UDPTransport(Transport):
    def __init__(self, session):
        super().__init__(session)
        self.caddr = self.session.addr[0]
        self.track_map = {}
        self.socks = {}

    def conf_track(self, track):
        """Set target port for tracks"""
        if track.track_id in self.track_map:
            track.ffmpeg_target_port = self.track_map[track.track_id]["s"][0]

    def on_play(self):
        """Prepare for playback by opening sockets"""
        for track in self.track_map:
            tsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            tsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tsock.bind(("0.0.0.0", self.track_map[track]["s"][0]))
            self.socks[track] = tsock


    def on_traffic(self, data, track_id, relay_id):
        """Decide on port and re-send data to client"""
        client_port = self.track_map[track_id]["c"][relay_id]
        self.socks[track_id].sendto(data, (self.caddr, client_port))


    def on_pause(self):
        """Close all sockets"""
        for sock in self.socks.values():
            sock.close()