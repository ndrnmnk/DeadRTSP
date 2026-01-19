import re
from secrets import randbelow
from configurable import legacy_signatures
from .config import Config

def detect_legacy_client(request):
    ua_match = re.search(r"User-Agent:\s*(.+)", request)
    if not ua_match:
        return False
    ua = ua_match.group(1).lower()
    return any(sig in ua for sig in legacy_signatures)

def generate_session_id(sessions_lock, sessions, max_attempts=10):
    for i in range(max_attempts):
        res = randbelow(9999999999)
        with sessions_lock:
            if res not in sessions.keys():
                return res
    raise RuntimeError(f"Could not allocate a unique session ID after {max_attempts} attempts. How rare is that, huh?")

def extract_cseq(request_text):
    cseq_match = re.search(r"CSeq:\s*(\d+)", request_text)
    if not cseq_match:
        return 0
    return cseq_match.group(1)

def extract_xsc(request_text):
    xsc_match = re.search(r'(?im)^x-sessioncookie:\s*([^\r\n]+)', request_text)
    if not xsc_match:
        return 0
    return xsc_match.group(1)

def extract_session_id(request):
    match = re.search(r'Session:\s*(\d+)', request)
    if match:
        return int(match.group(1))
    return None

def parse_range(request_text, default_value):
    # matches “Range: npt=START-END” or “Range: npt=START-”
    m = re.search(r'Range:\s*npt=(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?', request_text)
    if not m:
        return default_value, None
    start = float(m.group(1))
    end   = float(m.group(2)) if m.group(2) else None
    return start, end

def extract_cl(headers):
    m = re.search(r"Content-Length:\s*(\d+)", headers, flags=re.IGNORECASE)
    content_length = int(m.group(1)) if m else 0
    return content_length

def strip_addr(addr):
    addr = addr[7:]
    port_pos = addr.find(":")
    if port_pos == -1: pass
    else: addr = addr[:port_pos]
    return addr

def decide_multicast(session, is_td=False):
    if Config().get("multicast_admins") and session.multicast_host: return True
    if is_td:
        if session.transport.watching == 0: return True
    return False