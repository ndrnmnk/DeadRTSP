import socket
import logging
import subprocess
from random import randint
from threading import Thread
from Utils import Config

class Track:
    def __init__(self, parent, tid, ssrc):
        self.session = parent
        self.track_id = tid
        self.ffmpeg_from_port = Config().get_free_port("relay")
        Config().port_set_used(self.ffmpeg_from_port)
        self.ssrc = ssrc

        self.ffmpeg_target_port = None
        self.selector = None  # list of ffmpeg options to select the correct track and payload type; provided separately before PLAY
        self.on_data = self.session.transport.on_traffic
        self.stream_loop = (self.session.live_mode == 1) and Config().get("stream_loop")

        self.ts_offset = None
        self.clock_rate = 0
        self.proc = None
        self.relays = [None, None]
        self.relay_socks = []

        if Config().get("seq_start_at_one"): self.last_seq = 0
        else: self.last_seq = randint(0, 65534)

        if Config().get("zero_initial_ts"): self.initial_ts_offset = 0
        else: self.initial_ts_offset = randint(10000, 65534)
        if Config().get("random_ts"): self.ts_offset = 0


    def get_rtpinfo(self, zero_rtptime):
        if not zero_rtptime:
            rtptime = int(self.session.play_offset*self.clock_rate) + self.initial_ts_offset
        else:
            rtptime = 0
        return f"url={self.session.url}/trackID={self.track_id};seq={self.last_seq+1};rtptime={rtptime}"

    def on_play(self, start_time=0, end_time=None):
        cmd = [
            "ffmpeg", "-loglevel", "error",
            "-ss", str(start_time), *(["-to", str(end_time)] if end_time is not None else []),
            *(["-stream_loop", "-1"] if self.stream_loop else []), "-re",
            "-i", self.session.content_source,
            "-ssrc", str(self.ssrc), "-seq", str(self.last_seq+1),
            *self.selector, "-f", "rtp",
            f"rtp://127.0.0.1:{self.ffmpeg_target_port}/?localport={self.ffmpeg_from_port}"
        ]  # ffmpeg uses self.server_ports[0]+1 for RTCP by default
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL)

        self.relays[0] = Thread(target=self.patch_rtp, args=(self.ffmpeg_target_port,))
        self.relays[0].start()
        if not Config().get("disable_rtcp"):
            self.relays[1] = Thread(target=self.patch_outgoing_rtcp, args=(self.ffmpeg_target_port + 1,))
            self.relays[1].start()


    def on_pause(self):
        for sock in self.relay_socks:  # seems faster than using Event()
            sock.close()
        self.relay_socks = []
        self.ts_offset = None
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def teardown(self):
        self.on_pause()
        Config().port_set_free(self.ffmpeg_from_port)
        Config().port_set_free(self.ffmpeg_target_port)


    def patch_rtp(self, from_port):
        """Change timestamps in RTP packets, record seq and send to transport class"""
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp_socket.settimeout(1)
            udp_socket.bind(("127.0.0.1", from_port))
            self.relay_socks.append(udp_socket)
        except OSError:
            logging.error(f"Port {from_port} is already in use; not relaying(session {self.session.session_id}, track {self.track_id})")
            return
        # try:
        while True:
            try: data, _ = udp_socket.recvfrom(65536)
            except socket.timeout: continue
            seq = int.from_bytes(data[2:4], "big")
            # if not seq: continue
            self.last_seq = seq
            ts = int.from_bytes(data[4:8], "big")

            if self.ts_offset is None:
                if ts == 0: continue  # may get 0 once after resuming playback
                self.ts_offset = int(self.clock_rate*self.session.play_offset) - ts + self.initial_ts_offset

            new_ts = ts + self.ts_offset
            if new_ts > 0xFFFFFFFF or new_ts < 0:
                new_ts = (ts + self.ts_offset) & 0xFFFFFFFF
                self.ts_offset = (new_ts - ts) & 0xFFFFFFFF
            new_ts_bytes = new_ts.to_bytes(4, "big")
            data = data[:4] + new_ts_bytes + data[8:]

            self.on_data(data, self.track_id, 0)
        # except Exception as e:
        #     logging.error(f"Track stopped: {e}")
        #     udp_socket.close()

    def patch_outgoing_rtcp(self, from_port):
        """Change timestamps in RTCP sender report packets and forward to transport class"""
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp_socket.settimeout(1)
            udp_socket.bind(("127.0.0.1", from_port))
            self.relay_socks.append(udp_socket)
        except OSError:
            logging.error(f"Port {from_port} is already in use; not relaying(session {self.session.session_id}, track {self.track_id})")
            return
        try:
            while True:
                try: data, _ = udp_socket.recvfrom(65536)
                except socket.timeout: continue

                if data[1] == 200:
                    if self.ts_offset is None: continue
                    ts = int.from_bytes(data[16:20], "big")
                    new_ts = ts + self.ts_offset
                    new_ts_bytes = new_ts.to_bytes(4, "big")
                    data = data[:16] + new_ts_bytes + data[20:]

                self.on_data(data, self.track_id, 1)
        except Exception as e:
            logging.error(f"RTCP relay stopped stopped: {e}")
            udp_socket.close()