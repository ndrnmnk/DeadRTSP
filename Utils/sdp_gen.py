from secrets import randbelow
import subprocess
import json

def get_video_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'format=duration', '-of', 'json', file_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)

        if result.returncode != 0:
            return None

        info = json.loads(result.stdout)
        duration = info.get("format", {}).get("duration", None)

        # Return duration as float, or none if not found
        return float(duration) if duration is not None else None

    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return None

def generate_sdp(input_path, client_ip, port, is_live=False, compat=False):
    # Get track count
    vid_tracks = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=index", "-print_format", "json", input_path],
                   check=True, capture_output=True, text=True)
    vtracks_res = json.loads(vid_tracks.stdout)
    vid_tracks = len(vtracks_res["streams"])
    aud_tracks = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-print_format", "json", input_path],
                   check=True, capture_output=True, text=True)
    atracks_res = json.loads(aud_tracks.stdout)
    aud_tracks = len(atracks_res["streams"])

    if compat:
        is_live = True
        vid_tracks = min(1, vid_tracks)
        aud_tracks = min(1, aud_tracks)

    sdp_headers = []
    ssrcs = []
    rates = []
    sdp_media_sections = []
    track_id = 0

    # Generate video SDP for each video track
    for i in range(vid_tracks):
        video_res = subprocess.run([
            "ffmpeg", "-loglevel", "error", "-re", "-t", "1", "-i", input_path,
            "-map", f"0:v:{i}", "-c:v", "copy", "-payload_type", "96",
            "-f", "rtp", f"rtp://127.0.0.1:{port}"
        ], capture_output=True, text=True, check=True)

        v_lines = video_res.stdout.splitlines(keepends=True)[1:]
        for line in v_lines:
            if line.startswith("m="):
                ssrcs.append(randbelow(2_147_483_648))
                sdp_media_sections.append(line)
                sdp_media_sections.append(f"c=IN IP4 {client_ip}\r\n")
                sdp_media_sections.append(f"a=control:trackID={track_id}\r\n")
                sdp_media_sections.append(f"a=ssrc:{ssrcs[-1]} cname:deadRTSP\r\n")
            elif line.startswith("a=") and not line.startswith("a=tool"):
                sdp_media_sections.append(line)
            elif not line.startswith("a=tool") and not sdp_headers:
                sdp_headers.append(line)  # Store header from first SDP
        rates.append(90000)
        track_id += 1

    # Generate audio SDP for each audio track
    for i in range(aud_tracks):
        audio_res = subprocess.run([
            "ffmpeg", "-loglevel", "error", "-re", "-t", "1", "-i", input_path,
            "-map", f"0:a:{i}", "-c:a", "copy", "-payload_type", "97",
            "-f", "rtp", f"rtp://127.0.0.1:{port}"
        ], capture_output=True, text=True, check=True)
        a_lines = audio_res.stdout.splitlines(keepends=True)[1:]

        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", f"a:{i}", "-show_entries",
                                "stream=codec_name,sample_rate,channels", "-of", "json", input_path], capture_output=True, text=True, check=True)
        info = json.loads(probe.stdout)["streams"][0]
        codec, rate, ch = info["codec_name"], info["sample_rate"], info["channels"]

        contains_rtpmap = any(line.startswith("a=rtpmap") for line in a_lines)

        fmt_lines = []
        if not contains_rtpmap:
            if codec == "mp3":
                fmt_lines.append(f"a=rtpmap:97 MPA/{rate}/{ch}\r\n")
            elif codec == "pcm_mulaw":
                fmt_lines.append(f"a=rtpmap:97 PCMU/{rate}/{ch}\r\n")
            else:
                fmt_lines.append(f"a=rtpmap:97 {codec.upper()}/{rate}/{ch}\r\n")

        for line in a_lines:
            if line.startswith("m="):
                ssrcs.append(randbelow(2_147_483_648))
                sdp_media_sections.append(line)
                for fmt in fmt_lines:
                    sdp_media_sections.append(fmt)
                sdp_media_sections.append(f"c=IN IP4 {client_ip}\r\n")
                sdp_media_sections.append(f"a=control:trackID={track_id}\r\n")
                sdp_media_sections.append(f"a=ssrc:{ssrcs[-1]} cname:deadRTSP\r\n")
            elif line.startswith("a=") and not line.startswith("a=tool"):
                sdp_media_sections.append(line)
            elif not line.startswith("a=tool") and not sdp_headers:
                sdp_headers.append(line)

        rates.append(int(rate))
        track_id += 1

    sdp_headers.append("a=control:*\r\n")
    vid_duration = None
    if not is_live:
        vid_duration = get_video_duration(input_path)
        if vid_duration:
            sdp_headers.append(f"a=range:npt=0-{vid_duration}\r\n")
    res = "".join(sdp_headers + sdp_media_sections).replace("127.0.0.1", client_ip)
    # Convert to CRLF line endings
    res = res.replace('\r', '').replace('\n', '\r\n')
    return {"sdp": res, "vtracks": vid_tracks, "atracks": aud_tracks, "ssrcs": ssrcs, "rates": rates, "len": vid_duration}