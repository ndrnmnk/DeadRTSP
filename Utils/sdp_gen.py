from secrets import randbelow
import subprocess
import json

MAX_SSRC = 2_147_483_648

SDP_HEADER = ["v=0", "a=control:*"]


def parse_streams(input_path):
    """Gets video and audio tracks, as well as audio codec data"""
    streams_cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", input_path]
    proc = subprocess.run(streams_cmd, capture_output=True, text=True)
    res = json.loads(proc.stdout)
    vtracks = []
    atracks = []
    for idx, track in enumerate(res["streams"]):
        if track["codec_type"] == "video": vtracks.append(idx)
        elif track["codec_type"] == "audio": atracks.append(idx)
    return vtracks, atracks, res

def parse_track(input_path, track_id, ptype, port):
    """Extracts SDP for specific track using FFmpeg"""
    selector = "-c:v" if ptype == 96 else "-c:a"
    tracks_cmd = [ "ffmpeg", "-loglevel", "error", "-re", "-t", "1", "-i", input_path,
            "-map", f"0:{track_id}", selector, "copy", "-payload_type", str(ptype),
            "-f", "rtp", f"rtp://127.0.0.1:{port}"]

    r = subprocess.run(tracks_cmd, capture_output=True, text=True)
    res = r.stdout.splitlines()[1:]
    return res

def parse_sdp_media(sdp_lines, track_id, fmt=None):
    """Extracts SDP media data from partial SDP"""
    media = []
    ssrc = randbelow(MAX_SSRC)
    for line in sdp_lines:
        if line.startswith("m="):
            media.append(line)
            if fmt: media.extend(fmt)
            media.append("c=IN IP4 127.0.0.1")
            media.append(f"a=control:trackID={track_id}")
            media.append(f"a=ssrc:{ssrc} cname:deadRTSP")
        elif line.startswith("a=") and not line.startswith("a=tool"):
            media.append(line)

    return media, ssrc

def generate_sdp(input_path, target_ip, port, is_live=False, compat=False):
    """Generates SDP for the given input.
    Args:
        input_path (str): Path to the input
        target_ip (str): IP to use in SDP
        port (int): Port to use for generation
        is_live (bool): Don't report content duration if true
        compat (bool): Enables is_live and limits tracks to 1v+1a max"""
    # get amount of tracks and ffprobe
    vtracks, atracks, ffprobe_data = parse_streams(input_path)

    if compat:
        is_live = True
        # vtracks = min(1, vtracks)
        # atracks = min(1, atracks)

    ssrcs = []
    rates = []
    sdp_media = []

    # generate video sdp
    for track_id in vtracks:
        v_lines = parse_track(input_path, track_id, 96, port)
        sm, ssrc_temp = parse_sdp_media(v_lines, track_id, None)
        sdp_media.extend(sm)
        ssrcs.append(ssrc_temp)
        rates.append(90000)

    # generate audio sdp
    for track_id in atracks:
        a_lines = parse_track(input_path, track_id, 97, port)
        track_info = ffprobe_data["streams"][track_id]
        codec, rate, ch = track_info["codec_name"], track_info["sample_rate"], track_info["channels"]

        contains_rtpmap = any(line.startswith("a=rtpmap") for line in a_lines)
        fmt_lines = []
        if not contains_rtpmap:
            if codec == "mp3": fmt_lines.append(f"a=rtpmap:97 MPA/{rate}/{ch}")
            elif codec == "pcm_mulaw": fmt_lines.append(f"a=rtpmap:97 PCMU/{rate}/{ch}")
            else: fmt_lines.append(f"a=rtpmap:97 {codec.upper()}/{rate}/{ch}")

        sm, ssrc_temp = parse_sdp_media(a_lines, track_id, fmt_lines)
        sdp_media.extend(sm)
        ssrcs.append(ssrc_temp)

        rates.append(int(rate))

    headers = SDP_HEADER
    try: vid_duration = float(ffprobe_data["format"]["duration"])
    except: vid_duration = None
    if not is_live and vid_duration is not None:
        headers.append(f"a=range:npt=0-{vid_duration}")
    res = "\r\n".join(headers + sdp_media).replace("127.0.0.1", target_ip)
    # Convert to CRLF line endings
    res += "\r\n\r\n"
    return {"sdp": res, "vtracks": len(vtracks), "atracks": len(atracks), "ssrcs": ssrcs, "rates": rates, "len": vid_duration}
