from .transport_base import Transport
from Utils import Config
import socket

class MultTransport(Transport):
    def __init__(self, session):
        super().__init__(session)
        self.track_map = {}
        self.sock = None
        self.watching = 1  # modified by session classes

    def conf_track(self, track):
        """Set target port for tracks"""
        # These ports will be used in relays to patch RTP packets
        if track.track_id in self.track_map:
            p = Config().get_free_port("relay")
            Config().port_set_used(p)
            track.ffmpeg_target_port = p

    def on_play(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)

    def on_traffic(self, data, track_id, relay_id):
        """Decide on socket and re-send data to all clients"""
        target_port = self.track_map[track_id][relay_id]
        self.sock.sendto(data, (self.session.mcip, target_port))

    def on_pause(self):
        self.sock.close()

    def on_teardown(self):
        # free the ports
        self.on_pause()
        for ports in self.track_map.values():
            Config().port_set_free(ports[0])