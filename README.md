# DeadRTSP

A minimalistic RTSP server in Python designed to work with all FFmpeg-supported video formats, 
supporting both TCP and UDP, and capable of serving multiple clients simultaneously.

> [!IMPORTANT]
> This server supports seeking only with clients that use RTCP. This means, that clients like MPV won't seek correctly

### Features

- Supports all FFmpeg-compatible video formats (but video needs to have audio)
- TCP and UDP streaming modes
- Multiple simultaneous clients
- Supports pausing and seeking

###  VLC Desktop wouldn't work properly - it uses some custom RTSP dialect. Tested successfully with other players

---

### Installation
Make sure **ffmpeg** is installed and functional

```
git clone https://github.com/ndrnmnk/deadRTSP
cd deadRTSP
python3 -m venv venv; source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

### Configuration

- Video Source: Set your desired input in the `choose_video()` function in `main.py`. 
You can easily modify it to read from a file, pipe, or another stream for project integration.

- Server Settings: Customize protocols, ports and logging level in `config.yaml`.

- Legacy clients: If your client is legacy and doesn't work correctly, 
you can try adding it into `legacy_signatures` list. 
This edits some values in responses to make playback possible again.

### Why?

Most RTSP servers fail to support older feature phones. 
DeadRTSP was built from scratch to stream video to legacy devices — tested with a Nokia N85.

### Contributing
Pull requests, suggestions and reported issues are welcome. If it helps your weird device stream video, even better.

### Footage

![Demo](https://raw.githubusercontent.com/ndrnmnk/ndrnmnk/main/deadRTSP.gif)