import subprocess

def generate_sdp(video_name, client_ip, v_port, a_port):
    # Generate video SDP
    video_res = subprocess.run([
        "ffmpeg", "-loglevel", "error", "-re", "-t", "1", "-i", video_name, "-map", "0:v:0",
        "-c:v", "copy", "-payload_type", "96", "-f", "rtp", f"rtp://127.0.0.1:{v_port}"
    ], check=True, capture_output=True, text=True)

    # Generate audio SDP
    audio_res = subprocess.run([
        "ffmpeg", "-loglevel", "error", "-re", "-t", "1", "-i", video_name, "-map", "0:a:0",
        "-c:a", "copy", "-payload_type", "97", "-f", "rtp", f"rtp://127.0.0.1:{a_port}"
    ], check=True, capture_output=True, text=True)

    # Read ffmpegs output while skipping "SDP:" line
    v_lines = video_res.stdout.splitlines(keepends=True)[1:]
    a_lines = audio_res.stdout.splitlines(keepends=True)[1:]

    # Separate header and media sections
    header = []
    media = []

    for line in v_lines:
        if line.startswith("m="):
            media.append(line)
        elif not line.startswith("a=tool"):  # skip redundant metadata
            header.append(line)

    # Add video attributes (skip repeated tool line)
    video_attrs = [line for line in v_lines if line.startswith("a=") and not line.startswith("a=tool")]
    media.extend(video_attrs)

    # Add audio media and attributes
    for line in a_lines:
        if line.startswith("m="):
            media.append(line)
        elif line.startswith("a=") and not line.startswith("a=tool"):
            media.append(line)

    # Insert media-level c= and a=control lines after each m= line
    i = 0
    while i < len(media):
        if media[i].startswith("m=video"):
            media.insert(i + 1, f"c=IN IP4 {client_ip}\r\n")
            media.insert(i + 2, "a=control:trackID=0\r\n")
            i += 2
        elif media[i].startswith("m=audio"):
            media.insert(i + 1, f"c=IN IP4 {client_ip}\r\n")
            media.insert(i + 2, "a=control:trackID=1\r\n")
            i += 2
        else:
            i += 1

    # Now add session-level control and merge
    header.append("a=control:*\r\n")
    all_lines = header + media
    res = "".join(all_lines).replace("127.0.0.1", client_ip)

    # Convert to CRLF line endings
    res = res.replace('\r', '')
    res = res.replace('\n', '\r\n')

    print(res)
    return res

if __name__ == "__main__":
    generate_sdp("bad_apple.3gp", "127.0.0.1", 10002, 10004)