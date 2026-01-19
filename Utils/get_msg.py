def get_err(code):
    messages = {
        400: "RTSP/1.0 400 Bad Request",
        404: "RTSP/1.0 404 Not Found",
        416: "RTSP/1.0 416 Requested Range Not Satisfiable",
        455: "RTSP/1.0 455 Method Not Valid in This State",
        457: "RTSP/1.0 457 Invalid Range",
        461: "RTSP/1.0 461 Unsupported Transport",
        501: "RTSP/1.0 501 Not Implemented",
        -501: "HTTP/1.0 501 Not Implemented\r\nConnection: close"
    }
    return messages.get(code, "RTSP/1.0 500 Internal Server Error")

def get_http_resp():
    resp = (
            "HTTP/1.0 200 OK\r\n"
            "Content-Type: application/x-rtsp-tunnelled\r\n"
            "Cache-Control: no-store\r\n"
            "Pragma: no-cache\r\n"
            "Connection: keep-alive\r\n"
            "Content-Length: 4294967295\r\n"
            "\r\n"
        )
    return resp.encode()

def get_cmd_err_code(command):
    not_implemented = ("ANNOUNCE", "GET_PARAMETER", "RECORD", "REDIRECT", "SET_PARAMETER")
    for cmd in not_implemented:
        if cmd in not_implemented:
            return 501
    return 400