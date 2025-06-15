import re
import socket
import secrets
import logging
import threading
import subprocess
from config import Config
from sdp_gen import generate_sdp


# EDIT THIS FUNCTION TO CHANGE THE VIDEO
def choose_video(request):
    vid_list = ["bad_apple.3gp", "rickroll.mp4", "grief.3gp"]
    return vid_list[len(sessions)]



sessions = {}
sessions_lock = threading.Lock()

def generate_session_id(max_attempts=10):
    for i in range(max_attempts):
        res = secrets.randbelow(9999999999)
        with sessions_lock:
            if res not in sessions.keys():
                return res
    raise RuntimeError(f"Could not allocate a unique session ID after {max_attempts} attempts. How rare is that, huh?")

def extract_cseq(request_text):
    cseq_match = re.search(r"CSeq:\s*(\d+)", request_text)
    if not cseq_match:
        return 0
    return cseq_match.group(1)

def extract_session_id(request):
    match = re.search(r'Session:\s*(\d+)', request)
    if match:
        return int(match.group(1))
    return None

class RTSPTrack:
    def __init__(self, track_id, interleaved, interleaved_channels, client_ports, server_ports, transport_line):
        self.track_id = track_id
        self.interleaved = interleaved
        self.interleaved_channels = interleaved_channels
        self.client_ports = client_ports
        self.server_ports = server_ports
        self.transport = transport_line

    def teardown(self):
        Config().port_set_free(self.server_ports[0])

class RTSPSession:
    def __init__(self, conn, addr):
        self.tracks = {}
        self.processes = []
        self.tcp_relay_ports = []
        self.interleaved_channel_map = {}
        self.session_id = None
        self.video = None
        self.url = None
        self.relay_sockets = []
        self.teardown_lock = threading.Lock()
        self.torn_down = False

        self.conn = conn
        self.addr = addr

        self.buffer = b""
        self.last_activity = threading.Event()
        self.last_activity.set()

        threading.Thread(target=self.timeout_watchdog, daemon=True).start()
        try:
            while True:
                if len(self.buffer) < 1:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    self.buffer += chunk

                self.last_activity.set()
                if self.buffer[0] == 0x24:
                    self.handle_rtcp()
                else:
                    temp = self.handle_rtsp()
                    if temp == 0:
                        break
        except Exception as e:
            logging.warning(f"[{self.addr}]: Error: {e}")

    def handle_rtsp(self):
        # finish reading the request
        if b"\r\n\r\n" not in self.buffer:
            chunk = self.conn.recv(4096)
            if not chunk:
                return 0
            self.buffer += chunk
            return

        request_end = self.buffer.find(b"\r\n\r\n") + 4
        request_text = self.buffer[:request_end].decode('utf-8', errors='ignore')
        self.buffer = self.buffer[request_end:]

        ###############

        cseq = extract_cseq(request_text)
        logging.debug(f"[{self.addr}] received request:\n" + request_text)
        if "OPTIONS" in request_text:
            resp = (
                "RTSP/1.0 200 OK\r\n"
                f"CSeq: {cseq}\r\n"
                "Public: OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN\r\n\r\n"
            )
            self.conn.send(resp.encode())
        elif "DESCRIBE" in request_text:
            self.url = request_text.splitlines()[0].split()[1]
            self.video = choose_video(request_text)

            p1 = Config().get_free_port("sdp")
            Config().port_set_used(p1)
            p2 = Config().get_free_port("sdp")
            Config().port_set_used(p2)

            sdp = generate_sdp(self.video, self.addr[0], p1, p2)

            Config().port_set_free(p1)
            Config().port_set_free(p2)

            resp = (
                "RTSP/1.0 200 OK\r\n"
                f"CSeq: {cseq}\r\n"
                f"Content-Base: {self.url}/\r\n"
                "Content-Type: application/sdp\r\n"
                f"Content-Length: {len(sdp)}\r\n"
                "\r\n"
                f"{sdp}"
            )
            self.conn.send(resp.encode())
        elif "SETUP" in request_text:
            if not self.url:
                self.url = request_text.splitlines()[0].split()[1]
            self.session_id, track_id = self.parse_setup(request_text)

            # Register session if needed
            if self.session_id not in sessions:
                with sessions_lock:
                    sessions[self.session_id] = self

            self.conn.send(self.generate_setup_response(track_id, cseq).encode())
        elif "PLAY" in request_text:
            if self.tracks[0].interleaved:
                self.handle_play_tcp(cseq)
            else:
                self.handle_play_udp(cseq)
        elif "TEARDOWN" in request_text:
            self.teardown()
        else:
            logging.warning(f"[{self.addr}]: Unknown request:\n {request_text}")

    def handle_play_udp(self, cseq, tcp_bridge=None):
        if not tcp_bridge:
            logging.debug("Handling UDP")
            if 0 not in self.tracks or 1 not in self.tracks:
                logging.error("Not all tracks setup yet.")
                return

            response = (
                "RTSP/1.0 200 OK\r\n"
                f"CSeq: {cseq}\r\n"
                f"Session: {self.session_id}\r\n"
                f"RTP-Info: "
                f"url={self.url}/trackID=0;seq=0;rtptime=0,"
                f"url={self.url}/trackID=1;seq=0;rtptime=0\r\n"
                "\r\n"
            )
            self.conn.send(response.encode())

            ip = self.addr[0]
            client_ports = (self.tracks[0].client_ports[0], self.tracks[1].client_ports[0])
        else:
            ip = "127.0.0.1"
            client_ports = (tcp_bridge[0], tcp_bridge[1])

        server_ports = (self.tracks[0].server_ports[0], self.tracks[1].server_ports[0])

        video_cmd = [
            "ffmpeg", "-loglevel", "error", "-stream_loop", "-1", "-re", "-i", self.video, "-an", "-map", "0:v:0",
            "-c:v", "copy", "-payload_type", "96", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
            "-f", "rtp", f"rtp://{ip}:{client_ports[0]}/?localport={server_ports[0]}"
        ]

        audio_cmd = [
            "ffmpeg", "-loglevel", "error", "-stream_loop", "-1", "-re", "-i", self.video, "-vn", "-map", "0:a:0",
            "-c:a", "copy", "-payload_type", "97", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
            "-f", "rtp", f"rtp://{ip}:{client_ports[1]}/?localport={server_ports[1]}"
        ]
        try:
            self.processes = [
                subprocess.Popen(video_cmd, stdout=subprocess.DEVNULL),
                subprocess.Popen(audio_cmd, stdout=subprocess.DEVNULL)
            ]
        except Exception as e:
            logging.error(f"Failed to start video ffmpeg: {e}")

    def handle_play_tcp(self, cseq):
        logging.debug("Handling TCP")
        # 1) Send OK for PLAY
        url = self.url.rsplit("/trackID=", 1)[0]
        response = (
            "RTSP/1.0 200 OK\r\n"
            f"CSeq: {cseq}\r\n"
            f"Session: {self.session_id}\r\n"
            f"RTP-Info: "
            f"url={url}/trackID=0;seq=0;rtptime=0,"
            f"url={url}/trackID=1;seq=0;rtptime=0\r\n"
            "\r\n"
        )
        self.conn.send(response.encode())

        # 2) Prepare ports
        port1 = Config().get_free_port("relay")
        Config().port_set_used(port1)
        port2 = Config().get_free_port("relay")
        Config().port_set_used(port2)

        self.tcp_relay_ports.append(port1)
        self.tcp_relay_ports.append(port2)

        self.interleaved_channel_map = {0: port1, 1: port2}

        # 3) Launch ffmpeg (UDP -> loopback) for relaying to TCP
        self.handle_play_udp(cseq, tcp_bridge=self.interleaved_channel_map)

        # 4) Relay both RTP and RTCP for each track
        for track_id, track in self.tracks.items():
            rtp_chan, rtcp_chan = track.interleaved_channels
            base_port = self.interleaved_channel_map[track_id]

            # RTP relay
            threading.Thread(
                target=self.relay_udp_to_tcp,
                args=(base_port, rtp_chan),
                daemon=True
            ).start()

            # RTCP relay
            threading.Thread(
                target=self.relay_udp_to_tcp,
                args=(base_port + 1, rtcp_chan),
                daemon=True
            ).start()


    def relay_udp_to_tcp(self, local_port, interleaved_channel):
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_socket.bind(("127.0.0.1", local_port))
        self.relay_sockets.append(udp_socket)
        logging.debug(f"Relaying from UDP {local_port} to TCP channel {interleaved_channel}")

        try:
            while True:
                try:
                    data, _ = udp_socket.recvfrom(65536)
                    self.send_interleaved_rtp(interleaved_channel, data)
                except (BrokenPipeError, ConnectionResetError) as e:
                    logging.info(f"Connection closed by client, stopping relay: {e}")
                    self.teardown()
                    break
                except Exception as e:
                    logging.error(f"Unexpected error in relay_udp_to_tcp: {e}")
                    break
        finally:
            udp_socket.close()

    def send_interleaved_rtp(self, channel, rtp_packet):
        header = bytes([36, channel]) + len(rtp_packet).to_bytes(2, 'big')
        self.conn.sendall(header + rtp_packet)

    def parse_setup(self, request_text):
        session_id = extract_session_id(request_text) or generate_session_id()

        interleaved_channels = None
        client_ports = None

        track_match = re.search(r'trackID=(\d+)', request_text)

        track_id = int(track_match.group(1)) if track_match else 0

        lines = request_text.splitlines()
        transport_line = next((l for l in lines if l.lower().startswith("transport:")), "")
        transport_parts = transport_line.split(";")

        # Check what protocol client requested
        is_tcp = "RTP/AVP/TCP" in transport_line
        is_udp = "RTP/AVP" in transport_line and not is_tcp

        # To return "Unsupported protocol" later
        if (is_udp and PROTOCOL_MODE == 1) or (is_tcp and PROTOCOL_MODE == 2):
            return None, None

        # Prepare data for TCP
        if is_tcp or PROTOCOL_MODE == 3:
            logging.debug(f"[{self.addr}]: Preparing for TCP")
            for part in transport_parts:
                if "interleaved" in part:
                    channels = part.split("=")[1]
                    interleaved_channels = tuple(map(int, channels.split("-")))

            if not interleaved_channels:
                interleaved_channels = (track_id * 2, track_id * 2 + 1)

            if is_udp:
                transport_line = transport_line.replace("RTP/AVP", "RTP/AVP/TCP") + f";interleaved={interleaved_channels[0]}-{interleaved_channels[1]}"
            is_tcp = True

        # Prepare data for UDP
        elif is_udp or PROTOCOL_MODE == 4:
            logging.debug(f"[{self.addr}]: Preparing for UDP")
            for part in transport_parts:
                if "client_port" in part:
                    ports = part.split("=")[1]
                    client_ports = tuple(map(int, ports.split("-")))

            if not client_ports:
                t = Config().get_free_port()
                client_ports = (t, t+1)

            if is_tcp:
                transport_line = transport_line.replace("RTP/AVP/TCP", "RTP/AVP") + f";client_port={client_ports[0]}-{client_ports[1]}"
            is_udp = True


        # Get a pair of ports for further usage
        port = Config().get_free_port("udp")
        Config().port_set_used(port)
        server_ports = (port, port+1)
        # Save data
        track = RTSPTrack(track_id, is_tcp, interleaved_channels, client_ports, server_ports, transport_line)
        self.tracks[track_id] = track

        return session_id, track_id

    def generate_setup_response(self, track_id, cseq):
        if track_id is None:
            return (
                "RTSP/1.0 461 Unsupported Transport\r\n"
                f"CSeq: {cseq}\r\n"
                "\r\n"
            )
        track = self.tracks[track_id]

        if track.interleaved:
            transport = (
                "RTP/AVP/TCP;unicast;"
                f"interleaved={track.interleaved_channels[0]}-{track.interleaved_channels[1]}"
            )
        else:
            transport = (
                "RTP/AVP;unicast;"
                f"client_port={track.client_ports[0]}-{track.client_ports[1]};"
                f"server_port={track.server_ports[0]}-{track.server_ports[1]}"
            )

        return (
            "RTSP/1.0 200 OK\r\n"
            f"CSeq: {cseq}\r\n"
            f"Session: {self.session_id}\r\n"
            f"Transport: {transport}\r\n"
            "\r\n"
        )

    def handle_rtcp(self):
        if len(self.buffer) < 4:
            self.buffer += self.conn.recv(4096)
            return

        while len(self.buffer) >= 4 and self.buffer[0] == 0x24:
            channel = self.buffer[1]
            packet_len = int.from_bytes(self.buffer[2:4], byteorder='big')

            # Wait for full packet
            if len(self.buffer) < 4 + packet_len:
                self.buffer += self.conn.recv(4096)
                return

            packet_data = self.buffer[4:4 + packet_len]
            self.buffer = self.buffer[4 + packet_len:]

            if channel in self.interleaved_channel_map:
                udp_port = self.interleaved_channel_map[channel]
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
                    udp_socket.sendto(packet_data, ("127.0.0.1", udp_port))
            else:
                logging.warning(f"RTCP on unknown channel {channel}")

    def teardown(self):
        with self.teardown_lock:
            if self.torn_down:
                return
            # Kill all ffmpegs
            for proc in self.processes:
                if proc.poll() is None:
                    proc.terminate()
            self.processes = []
            # Free their ports
            for track_id, track in list(self.tracks.items()):
                track.teardown()
            self.tracks.clear()
            # Kill relay sockets
            for sock in self.relay_sockets:
                try:
                    sock.close()
                except Exception:
                    pass
            self.relay_sockets.clear()
            # Free all the TCP relay ports
            for port in self.tcp_relay_ports:
                Config().port_set_free(port)
            # Suicide
            with sessions_lock:
                if self.session_id in sessions:
                    sessions.pop(self.session_id, None)
            self.torn_down = True

    def timeout_watchdog(self):
        wait_time = Config().get("session_timeout")
        while True:
            self.last_activity.wait(wait_time)
            if not self.last_activity.is_set():
                logging.info(f"Connection from {self.addr} timed out")
                self.teardown()
                break
            self.last_activity.clear()

class RTSPServer:
    def __init__(self):
        # Open the TCP port
        port = Config().get("main_port")
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('', port))
        self.socket.listen(Config().get("max_sessions"))
        print(f"Started RTSP server at 0.0.0.0:{port}")

        self.handle_connections()

    def handle_connections(self):
        while True:
            conn, addr = self.socket.accept()
            logging.info(f"New connection from {addr}")
            t = threading.Thread(target=RTSPSession, args=(conn, addr), daemon=True)
            t.start()


if __name__ == "__main__":
    logging.basicConfig(level=Config().get("log_level", 40))

    PROTOCOL_MODE = Config().get("PROTOCOL_MODE")
    if PROTOCOL_MODE > 4 or PROTOCOL_MODE < 0 or type(PROTOCOL_MODE) is not int:
        logging.critical("Unsupported PROTOCOL_MODE. Exiting.")
        quit()
    RTSPServer()