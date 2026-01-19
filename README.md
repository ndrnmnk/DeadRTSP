# DeadRTSP

An RTSP server in Python designed to work with all FFmpeg-supported video formats.  
It's mainly designed to work with outdated clients like feature phones. 

> [!IMPORTANT]
> Seeking is unstable and very client-dependent. No idea how to make it better with vanilla FFmpeg.

### Features

- Supports all FFmpeg-compatible video formats
- TCP, UDP and HTTP transport modes
- unicast and multicast
- Live and VoD modes
- VoD allows for pausing and seeking

### Problems

MPV doesn't seek when `seq_start_at_zero` is not enabled.  
Multicast is untested

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

Configs can be found here:

- `configurable.py`: **video source** and **legacy client** user agents

- `config.yaml`: **supported protocols**, max connections, log level etc.

### Why?

Most RTSP servers fail to support older feature phones.  
DeadRTSP was initially made just to work with them — tested with a Nokia N85 and Nokia 6300.  
Later it was expanded to be an option for newer clients too

### Footage

![Demo](https://raw.githubusercontent.com/ndrnmnk/ndrnmnk/main/deadRTSP.gif)