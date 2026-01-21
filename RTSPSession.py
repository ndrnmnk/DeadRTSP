import time
import logging
import threading
from time import sleep
from base64 import b64decode

from Transports.mult_transport import MultTransport
from configurable import choose_source, detect_multicast
from Utils import *
from track import Track
from Transports import *

class RTSPSession:
    def __init__(self, conn, addr, sid, parent_server):
        # content-unrelated options
        self.parent_server = parent_server
        self.rconn = conn
        self.wconn = conn
        self.addr = addr
        self.session_id = sid
        self.xsc = None

        # content-related options
        self.tracks = {}
        self.expected_video_tracks = None
        self.expected_audio_tracks = None
        self.url = None
        self.content_source = None

        # state-related
        # states: 1 - init, 2 - ready, 3 - playing, 0 - torn down
        self.state = 1
        self.transport = None
        self.transport_mode = None # "udp_u", "tcp", "http", "udp_m"
        self.play_start_time = None
        self.play_offset = 0
        self.last_activity = threading.Event()
        self.last_activity.set()

        self.ssrcs = None
        self.rates = None
        self.duration = None
        self.prepare_mc = False
        self.mcip = None
        self.multicast_host = False

        self.compat_mode = Config().get("always_compat")
        # live mode; 0 - not live; 1 - forced live; 2 - true live
        self.live_mode = Config().get("force_live")

        threading.Thread(target=self.handle_requests).start()
        threading.Thread(target=self.timeout_watchdog, daemon=True).start()

    def handle_rtsp(self, request_text):
        cseq = extract_cseq(request_text)
        err = 0
        logging.debug(f"Received request:\n{request_text}")
        if "OPTIONS" in request_text:
            self.handle_options(request_text, cseq)
        elif "DESCRIBE" in request_text:
            if self.state >= 1: # init or above
                self.handle_describe(request_text, cseq)
            else: err = 455
        elif "SETUP" in request_text:
            if self.state in (1, 2): # init or ready
                self.handle_setup(request_text, cseq)
            else: err = 455
        elif "PLAY" in request_text:
            if self.state == 2: # ready
                self.handle_play(request_text, cseq)
            else:
                err = 455
        elif "PAUSE" in request_text:
            if self.state == 3: # playing
                self.handle_pause(cseq)
            else: err = 455
        elif "TEARDOWN" in request_text:
            if self.state >= 1:
                self.teardown(cseq)
            else: err = 455
        elif "GET / HTTP/1.1" in request_text:
            self.handle_http_get(request_text)
        elif "POST / HTTP/1.1" in request_text:
            self.handle_http_post(request_text)
        else:
            logging.warning(f"Unknown command:\n{request_text}")
            err = get_cmd_err_code(request_text)

        if err: self.send_err(err, cseq)

    def handle_options(self, request_text, cseq):
        self.compat_mode = self.compat_mode or detect_legacy_client(request_text)
        self.prepare_mc = detect_multicast(request_text)
        self.live_mode = self.live_mode or self.compat_mode or (self.prepare_mc and not Config().get("multicast_admins"))
        resp = [f"Public: OPTIONS, DESCRIBE, SETUP, PLAY, {"PAUSE, " if not self.live_mode else ""}TEARDOWN"]
        self.send_response(cseq, resp, False)

    def handle_describe(self, request_text, cseq):
        self.url = request_text.splitlines()[0].split()[1]

        self.content_source, temp = choose_source(request_text)
        if self.content_source is None:
            self.send_err(404, cseq)
            return
        if temp: self.live_mode = 2  # True live mode

        if self.prepare_mc:
            self.find_multicast_session()
            if self.multicast_host:
                last_oct = Config().get_mcip()
                if last_oct is not None:
                    Config().mcip_set_used(last_oct)
                    self.mcip = Config().get("mc_ip_base") + str(last_oct)
                    self.url = f"rtsp://{self.mcip}:8554"

        p = Config().get_free_port("sdp")
        Config().port_set_used(p)
        addr = strip_addr(self.url)
        res = generate_sdp(self.content_source, addr, p, self.live_mode, self.compat_mode)
        Config().port_set_free(p)

        sdp_bytes = res["sdp"].encode()
        resp = [
            f"Content-Base: {self.url}/",
            "Content-Type: application/sdp",
            f"Content-Length: {len(sdp_bytes)}"
        ]

        self.send_response(cseq, resp, False)
        logging.debug(f"SDP:\n{res["sdp"]}")
        self.wconn.send(sdp_bytes)

        self.expected_video_tracks = res["vtracks"]
        self.expected_audio_tracks = res["atracks"]
        self.rates = res["rates"]
        if not self.ssrcs:
            self.ssrcs = res["ssrcs"]
            self.state = 1  # init_s
            self.duration = res["len"]

    def handle_setup(self, request_text, cseq):
        """Detect transport type, redirect to parser if supported or send an error message"""
        track_match = re.search(r'trackID=(\d+)', request_text)
        track_id = int(track_match.group(1)) if track_match else 0

        lines = request_text.splitlines()
        transport_line = next((l for l in lines if l.lower().startswith("transport:")), "")

        # detect protocol
        is_http = self.transport_mode == "http"
        is_tcp = "RTP/AVP/TCP" in transport_line and not is_http
        is_udp_u = "RTP/AVP" in transport_line and not is_tcp and not is_http
        is_udp_m = "multicast" in transport_line and is_udp_u
        if is_udp_m: is_udp_u = False

        # check if protocol is supported; HTTP was checked in handle_http_get
        if is_tcp and not Config().get("allow_tcp"):
            self.send_err(461, cseq)
            return
        elif is_udp_u and not Config().get("allow_udp_unicast"):
            self.send_err(461, cseq)
            return
        elif is_udp_m and not (Config().get("allow_udp_multicast") and self.prepare_mc):
            self.send_err(461, cseq)
            return

        if is_tcp or is_http:
            if not self.transport:
                self.transport = TCPTransport(self)
            parse_tcp(transport_line, track_id, self.transport)
            self.transport_mode = "tcp" if is_tcp else "http"
        elif is_udp_u:
            if not self.transport:
                self.transport = UDPTransport(self)
            parse_udp(transport_line, track_id, self.transport)
            self.transport_mode = "udp_u"
        elif is_udp_m:
            self.transport_mode = "udp_m"
            if self.transport is None:
                self.find_multicast_session()
                self.state = 2  # ready
                if self.multicast_host:
                    self.transport = MultTransport(self)
            if not self.multicast_host:
                self.generate_setup_response(track_id, cseq)
                return
            parse_udp_m(track_id, self.transport)


        track = Track(self, track_id, self.ssrcs[track_id])
        if track_id < self.expected_video_tracks:
            track.selector = ["-an", "-map", f"0:v:{track_id}", "-c:v", "copy", "-payload_type", "96"]
            track.clock_rate = self.rates[track_id]
        else:
            track.selector = ["-vn", "-map", f"0:a:{track_id-self.expected_video_tracks}", "-c:a", "copy", "-payload_type", "97"]
            track.clock_rate = self.rates[track_id]
        self.tracks[track_id] = track
        self.transport.conf_track(track)
        self.generate_setup_response(track_id, cseq)
        self.state = 2  # ready

    def generate_setup_response(self, track_id, cseq):
        # only TCP and UDP unicast are implemented right now
        transport_line = "Transport: "
        if self.transport_mode in ("tcp", "http"):
            transport_line += (
                "RTP/AVP/TCP;unicast;"
                f"interleaved={self.transport.track_map[track_id][0]}-{self.transport.track_map[track_id][1]}"
            )
        elif self.transport_mode == "udp_u":
            transport_line += (
                "RTP/AVP;unicast;"
                f"client_port={self.transport.track_map[track_id]["c"][0]}-{self.transport.track_map[track_id]["c"][1]};"
                f"server_port={self.transport.track_map[track_id]["s"][0]}-{self.transport.track_map[track_id]["s"][1]}"
            )
        elif self.transport_mode == "udp_m":
            ttl = Config().get("multicast_ttl")
            transport_line += (
                f"RTP/AVP/UDP;multicast;destination={strip_addr(self.url)};"
                f"port={self.transport.track_map[track_id][0]}-{self.transport.track_map[track_id][1]};"
                f"ttl={ttl}"
            )
        self.send_response(cseq, [transport_line])

    def find_multicast_session(self):
        """Finds the session with the same source file and gets its Transport instance"""
        for session in self.parent_server.sessions.values():
            if session is self: continue
            if session.transport_mode == "udp_m" and session.content_source == self.content_source:
                self.transport = session.transport
                self.transport.watching += 1
                self.tracks = session.tracks
                return
        self.multicast_host = True

    def handle_http_get(self, request):
        self.transport_mode = "http"
        self.xsc = extract_xsc(request)
        logging.debug(f"xsc: {self.xsc}")
        if Config().get("allow_http"):
            self.wconn.send(get_http_resp())
        else:
            self.send_err(-501, 0)

    def handle_http_post(self, headers):
        self.transport_mode = "http"
        swapped = False
        self.xsc = extract_xsc(headers)
        for session in self.parent_server.sessions.values():
            if session is self: continue
            if session.xsc == self.xsc:
                self.wconn = session.rconn
                logging.debug(f"HTTP mode: swapped connection successfully")
                session.teardown(None)
                swapped = True
                break
        if not swapped:
           logging.error("HTTP mode: failed to find session with xsc: %s", self.xsc)
        self.rconn.send(get_http_resp())

    def handle_play(self, request, cseq):
        self.transport.on_play()
        # reuse old offset or extract new one from request
        start_time, end_time = parse_range(request, self.play_offset)  # self.play_offset is a default value
        to_err = False
        if self.live_mode and start_time != self.play_offset: to_err = True
        if end_time is not None and end_time < start_time: to_err = True
        if self.transport_mode == "udp_m" and not decide_multicast(self) and start_time != self.play_offset: to_err = True
        if to_err:
            self.send_err(457, cseq)
            return

        if not self.live_mode and self.duration is not None:
            if start_time > self.duration:
                self.send_err(416, cseq)
                return
            if end_time is not None and end_time > self.duration: end_time = self.duration
        self.play_offset = start_time

        # collect RTP-Info from tracks
        rtp_info = []
        zero_rtptime = self.compat_mode or Config().get("report_zero_rtptime")
        for track in self.tracks.values():
            if not self.transport_mode == "udp_m" or self.multicast_host:
                while track.proc: sleep(0.1)
            rtp_info.append(track.get_rtpinfo(zero_rtptime))

        self.send_response(cseq, [f"Range: npt={self.play_offset:.3f}-", f"RTP-Info: {",".join(rtp_info)}"])
        self.state = 3  # playing
        if not self.transport_mode == "udp_m" or self.multicast_host:
            for track in self.tracks.values():
                track.on_play(self.play_offset, end_time)
        self.play_start_time = time.monotonic()

    def handle_pause(self, cseq):
        if self.live_mode or (self.transport_mode == "udp_m" and not decide_multicast(self)):
            self.send_err(455, cseq)
            return

        self.play_offset += time.monotonic() - self.play_start_time
        self.play_start_time = None
        self.send_response(cseq, [])
        self.transport.on_pause()
        self.state = 2  # ready
        for t in self.tracks.values():
            t.on_pause()

    def teardown(self, cseq):
        td_tracks = True
        if self.transport_mode == "udp_m":
            self.transport.watching -= 1
            td_tracks = decide_multicast(self, True)
        if td_tracks:
            for track in self.tracks.values(): track.teardown()
            if self.transport: self.transport.on_teardown()
            if self.mcip:
                octet = int(self.mcip.split(".")[-1])
                Config().mcip_set_free(octet)

        if cseq is not None:
            try: self.send_response(cseq, [])
            except BrokenPipeError: pass
            self.rconn.close()
            self.wconn.close()

        self.state = 0  # torn down
        self.parent_server.delete_session(self.session_id)

    def handle_requests(self):
        try:
            buffer = b""
            while True:

                self.last_activity.set()
                data = self.rconn.recv(1024)
                if not data: break
                buffer += data

                while True:
                    try: buffer_d = b64decode(buffer, validate=False)
                    except: buffer_d = b""

                    parse_b64 = False
                    headers_end = buffer.find(b"\r\n\r\n")
                    headers_end_d = buffer_d.find(b"\r\n\r\n")

                    if headers_end == -1: parse_b64 = True
                    else: headers_end += 4
                    if parse_b64 and headers_end_d == -1: break
                    else: headers_end_d += 4

                    if not parse_b64:
                        headers = buffer[:headers_end].decode("utf-8", errors="ignore")
                        buffer = buffer[headers_end:]
                        self.handle_rtsp(headers)
                    else:
                        headers = buffer_d[:headers_end_d].decode("utf-8", errors="ignore")
                        buffer = b""
                        self.handle_rtsp(headers)
        except Exception as e:
            logging.warning(f"[{self.addr}]: Error: {e}")

    def send_response(self, cseq, data, add_session=True):
        resp = f"RTSP/1.0 200 OK\r\nCSeq: {cseq}\r\n"
        if add_session: resp += f"Session: {self.session_id}\r\n"
        for s in data: resp += s + "\r\n"
        resp += "\r\n"

        logging.debug(f"Sending response:\n{resp}")
        resp_bytes = resp.encode()
        self.wconn.send(resp_bytes)

    def send_err(self, code, cseq=None):
        resp = get_err(code) + "\r\n"
        if cseq is not None:
            resp += f"CSeq: {cseq}\r\n"
        resp += "\r\n"
        self.wconn.send(resp.encode())

    def timeout_watchdog(self):
        wait_time = Config().get("session_timeout")
        while True:
            self.last_activity.wait(wait_time)
            if not self.last_activity.is_set() and not self.state == "torn_down":
                logging.info(f"Connection from {self.addr} timed out")
                if self.state != 0: self.teardown(None)
                break
            self.last_activity.clear()