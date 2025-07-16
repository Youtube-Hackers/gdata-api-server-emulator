import re
import sys
import requests

class GetVideo:
    _PLAYER_URL = (
        "https://www.googleapis.com/youtubei/v1/player"
        "?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
    )

    def fetch_video_data(self, video_id):
        payload = {
            "context": {
                "client": {
                    "hl": "en",
                    "gl": "US",
                    "clientName": "ANDROID",
                    "clientVersion": "19.02.39",
                    "androidSdkVersion": 34
                }
            },
            "videoId": video_id
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "com.google.android.youtube/19.02.39 (Linux; U; Android 14) gzip"
        }
        r = requests.post(self._PLAYER_URL, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()

    def get_stream_url(self, formats, preference="highest"):
        candidates = []
        for f in formats:
            mime = f.get("mimeType", "")
            if not mime.startswith("video/mp4"):
                continue
            if "audioQuality" not in f:
                continue
            height = f.get("height", 0) or 0
            candidates.append((height, f))

        if not candidates:
            return None, None

        candidates.sort(key=lambda x: x[0])
        if preference == "lowest":
            chosen = candidates[0][1]
        elif preference == "highest":
            chosen = candidates[-1][1]
        elif isinstance(preference, (int, str)) and str(preference).endswith("p"):
            want = int(str(preference)[:-1])
            found = [f for h, f in candidates if h == want]
            chosen = found[0] if found else candidates[-1][1]
        else:
            chosen = candidates[-1][1]

        return chosen, chosen.get("contentLength", 0)

def extract_video_id(url_or_id):
    patterns = [
        r"v=([0-9A-Za-z_-]{11})",
        r"youtu\.be/([0-9A-Za-z_-]{11})",
        r"youtube\.com/embed/([0-9A-Za-z_-]{11})",
        r"^([0-9A-Za-z_-]{11})$"
    ]
    for p in patterns:
        m = re.search(p, url_or_id)
        if m:
            return m.group(1)
    sys.exit("Invalid YouTube URL or ID.")
