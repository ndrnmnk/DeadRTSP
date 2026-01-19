from .config import Config

def parse_udp(tline, track_id, transport):
    parts = tline.split(";")
    for part in parts:
        if "client_port" in part:
            ports = part.split("=")[1]
            client_ports = tuple(map(int, ports.split("-")))
    if not client_ports:
        t = Config().get_free_port()
        client_ports = (t, t + 1)

    server_port = Config().get_free_port("udp")
    Config().port_set_used(server_port)
    transport.track_map[track_id] = {"c": client_ports, "s": tuple([server_port, server_port+1])}

def parse_tcp(tline, track_id, transport):
    channels = []
    parts = tline.split(";")

    for part in parts:
        if "interleaved" in part:
            channels_str = part.split("=")[1]
            channels = map(int, channels_str.split("-"))

    if not channels:
        channels = [track_id*2, track_id*2+1]

    transport.track_map[track_id] = tuple(channels)

def parse_udp_m(track_id, transport):
    server_port = Config().get_free_port("udp")
    Config().port_set_used(server_port)
    transport.track_map[track_id] = tuple([server_port, server_port+1])