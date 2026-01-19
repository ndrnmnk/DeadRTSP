import socket
import logging
import threading
from Utils import Config, generate_session_id
from RTSPSession import RTSPSession


class RTSPServer:
    def __init__(self):
        port = Config().get("main_port")
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('', port))
        self.socket.listen(Config().get("max_connections"))
        print(f"Started RTSP server at port {port}")

        self.sessions = {}
        self.sessions_lock = threading.Lock()

        self.handle_connections()

    def handle_connections(self):
        while True:
            conn, addr = self.socket.accept()
            logging.info(f"New connection from {addr}")
            self.new_session(conn, addr)

    def new_session(self, conn, addr):
        sid = generate_session_id(self.sessions_lock, self.sessions)
        with self.sessions_lock:
            self.sessions[sid] = RTSPSession(conn, addr, sid, self)

    def delete_session(self, sid):
        with self.sessions_lock:
            del self.sessions[sid]


if __name__ == "__main__":
    logging.basicConfig(level=Config().get("log_level", 40))
    RTSPServer()