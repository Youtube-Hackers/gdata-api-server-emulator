import json
import re
import base64
import urllib.parse
import requests
from html import escape
import io
import os
import sys
import time
import argparse
from typing import List, Dict, Optional, Tuple
import unicodedata
from comments import YoutubeCommentDownloader, SORT_BY_POPULAR, SORT_BY_RECENT

YOUTUBE_INNERTUBE_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
YOUTUBE_API_URL = f"https://www.youtube.com/youtubei/v1/search?key={YOUTUBE_INNERTUBE_API_KEY}"
YOUTUBE_API_BROWSE_URL = f"https://www.youtube.com/youtubei/v1/browse?key={YOUTUBE_INNERTUBE_API_KEY}"

CLIENT_CONTEXT = {
    "client": {
        "clientName": "WEB",
        "clientVersion": "2.20250710.09.00",
        "hl": "en",
        "gl": "US",
    }
}

TRENDING_PARAMS = {
    "music": "4gINGgt5dG1hX2NoYXJ0cw%3D%3D",
    "gaming": "4gIcGhpnYW1pbmdfY29ycHVzX21vc3RfcG9wdWxhcg%3D%3D",
    "movies": "4gIKGgh0cmFpbGVycw%3D%3D"
}

INDENT = 4

class Thumbnails:
    def __init__(self):
        self.default = None
        self.medium = None
        self.high = None
        self.standard = None
        self.maxres = None
    
    def load(self, thumbnail_data: List[Dict]) -> 'Thumbnails':
        for thumb in thumbnail_data:
            url = thumb.get('url')
            if not url:
                continue
            
            if 'default' in url:
                self.default = url
            elif 'mqdefault' in url:
                self.medium = url
            elif 'hqdefault' in url:
                self.high = url
            elif 'sddefault' in url:
                self.standard = url
            elif 'maxresdefault' in url:
                self.maxres = url
        return self

class VideoCompact:
    def __init__(self, client: 'Client', channel: Optional['BaseChannel'] = None):
        self.client = client
        self.channel = channel
        self.id = None
        self.title = None
        self.thumbnails = Thumbnails()
        self.duration = None
        self.view_count = None
        self.published_at = None
    
    def load(self, data: Dict) -> 'VideoCompact':
        self.id = data.get('videoId')
        self.title = data.get('title', {}).get('simpleText') or \
                    ''.join([t.get('text', '') for t in data.get('title', {}).get('runs', [])])
        
        thumbnails = data.get('thumbnail', {}).get('thumbnails', [])
        self.thumbnails.load(thumbnails)
        duration_text = data.get('lengthText', {}).get('simpleText', '')
        self.duration = duration_text
        view_count_text = data.get('viewCountText', {}).get('simpleText', '')
        self.view_count = view_count_text
        published_text = data.get('publishedTimeText', {}).get('simpleText', '')
        self.published_at = published_text
        
        return self

class Client:
    BASE_URL = "https://www.youtube.com/youtubei/v1"
    INNERTUBE_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
    INNERTUBE_CLIENT_NAME = "WEB"
    INNERTUBE_CLIENT_VERSION = "2.20250710.09.00"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0',
            'Accept-Language': 'en-US,en;q=0.5',
            'Content-Type': 'application/json',
        })
    
    def _post(self, endpoint: str, data: Dict) -> Dict:
        payload = {
            'context': {
                'client': {
                    'hl': 'en',
                    'gl': 'US',
                    'clientName': self.INNERTUBE_CLIENT_NAME,
                    'clientVersion': self.INNERTUBE_CLIENT_VERSION,
                }
            },
            **data
        }
        
        response = self.session.post(
            f"{self.BASE_URL}{endpoint}",
            params={'key': self.INNERTUBE_API_KEY},
            json=payload
        )
        
        return response.json()

class ChannelVideos:
    def __init__(self, client: 'Client', channel_id: str):
        self.client = client
        self.channel_id = channel_id
        self.items = []
        self.continuation = None
    
    def fetch(self) -> Tuple[List[VideoCompact], Optional[str]]:
        params = "EgZ2aWRlb3PyBgQKAjoA"
        
        data = {
            'browseId': self.channel_id,
            'params': params,
            'continuation': self.continuation
        }
        
        response = self.client._post('/browse', data)
        
        items = self._parse_video_data(response)
        continuation = self._get_continuation_from_items(items)
        videos = []
        
        for item in items:
            if 'videoRenderer' in item:
                video = VideoCompact(self.client).load(item['videoRenderer'])
                videos.append(video)
            elif 'richItemRenderer' in item:
                if 'videoRenderer' in item['richItemRenderer']['content']:
                    video = VideoCompact(self.client).load(item['richItemRenderer']['content']['videoRenderer'])
                    videos.append(video)
        
        return videos, continuation
    
    def _parse_video_data(self, data: Dict) -> List[Dict]:
        tabs = data.get('contents', {}).get('twoColumnBrowseResultsRenderer', {}).get('tabs', [])
        for tab in tabs:
            tab_renderer = tab.get('tabRenderer', {})
            if tab_renderer.get('title') == 'Videos':
                content = tab_renderer.get('content', {}).get('richGridRenderer', {})
                if content:
                    return content.get('contents', [])
                
                content = tab_renderer.get('content', {}).get('sectionListRenderer', {})
                if content:
                    items = []
                    for section in content.get('contents', []):
                        item_section = section.get('itemSectionRenderer', {})
                        if item_section:
                            items.extend(item_section.get('contents', []))
                    return items
        
        return data.get('contents', {}).get('richGridRenderer', {}).get('contents', [])
    
    def _get_continuation_from_items(self, items: List[Dict]) -> Optional[str]:
        for item in items:
            if 'continuationItemRenderer' in item:
                return item['continuationItemRenderer'].get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
        return None
    
    def next(self, count: int = 1) -> List[VideoCompact]:
        new_videos = []
        for _ in range(count):
            if not self.continuation and self.items:
                break
            
            videos, continuation = self.fetch()
            self.continuation = continuation
            new_videos.extend(videos)
        
        self.items.extend(new_videos)
        return new_videos

def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def extract_length_text_and_seconds(vd):
    length_obj = vd.get("lengthText", {})
    simple_text = length_obj.get("simpleText")
    accessible_label = (
        length_obj.get("accessibility", {})
                  .get("accessibilityData", {})
                  .get("label", "")
    )

    result = None
    seconds = 0

    if simple_text:
        result = {
            "simpleText": simple_text,
            "accessibility": {
                "accessibilityData": {"label": accessible_label}
            }
        }
        try:
            parts = list(map(int, simple_text.split(":")))
            if len(parts) == 3:
                seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
            elif len(parts) == 2:
                seconds = parts[0] * 60 + parts[1]
            elif len(parts) == 1:
                seconds = parts[0]
        except:
            seconds = 0

    return result, seconds

def extract_videos_from_items(items):
    videos = []
    for item in items:
        if "videoRenderer" in item:
            videos.append(item["videoRenderer"])
        elif "gridVideoRenderer" in item:
            videos.append(item["gridVideoRenderer"])
        elif "carouselShelfRenderer" in item or "richShelfRenderer" in item:
            contents = (
                item.get("carouselShelfRenderer", {}).get("contents", [])
                or item.get("richShelfRenderer", {}).get("contents", [])
            )
            videos.extend(extract_videos_from_items(contents))
        elif "shelfRenderer" in item:
            contents = item.get("shelfRenderer", {}) \
                           .get("content", {}) \
                           .get("expandedShelfContentsRenderer", {}) \
                           .get("items", [])
            videos.extend(extract_videos_from_items(contents))
    return videos

def deduplicate_videos(videos):
    seen = set()
    out = []
    for v in videos:
        vid = v.get("videoId")
        if vid and vid not in seen:
            seen.add(vid)
            out.append(v)
    return out

def parse_view_count(view_count_text):
    text = (view_count_text or "").lower().replace("views", "").strip()
    try:
        if "k" in text:
            return int(float(text.replace("k", "")) * 1_000)
        if "m" in text:
            return int(float(text.replace("m", "")) * 1_000_000)
        digits = "".join(filter(str.isdigit, text))
        return int(digits) if digits else 0
    except:
        return 0

def to_json(comment, indent=4):
    try:
        comment_str = json.dumps(comment, ensure_ascii=False, indent=indent)
        if indent is None:
            return comment_str
        padding = ' ' * (2 * indent) if indent else ''
        return ''.join(padding + line for line in comment_str.splitlines(True))
    except Exception as e:
        print(f"Error serializing JSON: {str(e)}")
        return "{}"

def text_to_parsed_content(text):
    try:
        text = unicodedata.normalize('NFC', text.strip())
    except Exception as e:
        print(f"Error normalizing text: {str(e)}")
        text = text.strip()
    
    nodes = []
    for line in text.split('\n'):
        current_nodes = []
        initial_node = {"text": line}
        current_nodes.append(initial_node)

        url_pattern = r"https?://[^\s]*"
        for url_match in re.finditer(url_pattern, line):
            last_node = current_nodes[-1]
            split_text = last_node["text"].split(url_match.group(0))
            last_node["text"] = split_text[0]
            current_nodes[-1] = last_node
            current_nodes.append({
                "text": url_match.group(0),
                "navigationEndpoint": {"urlEndpoint": {"url": url_match.group(0)}}
            })
            if len(split_text) > 1:
                current_nodes.append({"text": split_text[1]})
            else:
                current_nodes.append({"text": ""})

        last_node = current_nodes[-1]
        last_node["text"] = last_node["text"] + "\n"
        current_nodes[-1] = last_node

        nodes.extend(current_nodes)

    return {"runs": nodes}

def content_to_comment_html(runs, video_id=""):
    html_array = []
    for run in runs:
        if not run:
            continue
        try:
            text = unicodedata.normalize('NFC', escape(run.get("text", "")))
        except Exception as e:
            print(f"Error normalizing run text: {str(e)}")
            text = escape(run.get("text", ""))
        
        if run.get("navigationEndpoint"):
            url = run["navigationEndpoint"].get("urlEndpoint", {}).get("url", "")
            if url:
                if "youtu.be" in url or "youtube.com" in url:
                    if "youtu.be" in url:
                        video_id_match = re.search(r"youtu\.be/([^?]+)", url)
                        if video_id_match:
                            text = f'<a href="/watch?v={video_id_match.group(1)}">{text}</a>'
                    elif "/redirect" in url:
                        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                        text = f'<a href="{params.get("q", [text])[0]}">{text}</a>'
                    else:
                        text = f'<a href="{url}">{text}</a>'
                else:
                    text = f'<a href="{url}">{text}</a>'
        if run.get("bold"):
            text = f"<b>{text}</b>"
        if run.get("strikethrough"):
            text = f"<s>{text}</s>"
        if run.get("italics"):
            text = f"<i>{text}</i>"
        if run.get("emoji") and run["emoji"].get("isCustomEmoji"):
            emoji_image = run["emoji"].get("image", {})
            emoji_alt = emoji_image.get("accessibility", {}).get("accessibilityData", {}).get("label", text)
            emoji_thumb = emoji_image.get("thumbnails", [{}])[0]
            if emoji_thumb and emoji_thumb.get("url"):
                text = (f'<img alt="{emoji_alt}" src="/ggpht{urllib.parse.urlparse(emoji_thumb.get("url", "")).path}" '
                        f'title="{emoji_alt}" width="{emoji_thumb.get("width", "")}" '
                        f'height="{emoji_thumb.get("height", "")}" class="channel-emoji" />')
            else:
                text = emoji_alt
        html_array.append(text.rstrip('\ufeff'))
    return "".join(html_array)

def parse_content(content, video_id=""):
    try:
        if content.get("simpleText"):
            return unicodedata.normalize('NFC', escape(content["simpleText"].rstrip('\ufeff')))
        elif content.get("runs"):
            html_content = content_to_comment_html(content["runs"], video_id)
            text = re.sub(r'<br\s*/?>', '\n', html_content, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text)
            text = unicodedata.normalize('NFC', text.strip())
            return text
        return ""
    except Exception as e:
        print(f"Error parsing content: {str(e)}")
        return ""

def innertube_comments(video_id, max_results=20, sort_by="top", language="en"):
    try:
        sort = SORT_BY_POPULAR if sort_by == "top" else SORT_BY_RECENT
        downloader = YoutubeCommentDownloader()
        comments = []
        count = 0
        start_time = time.time()
        for comment in downloader.get_comments(video_id, sort_by=sort, language=language):
            if count >= max_results:
                break

            text = parse_content(text_to_parsed_content(comment.get("text", "")), video_id)
            author = unicodedata.normalize('NFC', comment.get("author", ""))
            replies = []
            comments.append({
                "author": author,
                "text": text,
                "replies": replies
            })
            count += 1

        return comments
    except Exception as e:
        print(f"Error {video_id}: {str(e)}")
        return []

def produce_continuation(video_id, cursor="", sort_by="top"):
    object = {
        "2:embedded": {
            "2:string": video_id,
            "25:varint": 0,
            "28:varint": 1,
            "36:embedded": {
                "5:varint": -1,
                "8:varint": 0,
            },
            "40:embedded": {
                "1:varint": 4,
                "3:string": "https://www.youtube.com",
                "4:string": "",
            },
        },
        "3:varint": 6,
        "6:embedded": {
            "1:string": cursor,
            "4:embedded": {
                "4:string": video_id,
                "6:varint": 0 if sort_by == "top" else 1,
            },
            "5:varint": 20,
        },
    }
    encoded = base64.urlsafe_b64encode(json.dumps(object).encode()).decode()
    return urllib.parse.quote(encoded)

def innertube_search(query, region="US", max_results=100):
    payload = {
        "context": CLIENT_CONTEXT,
        "query": query,
        "params": ""
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": f"en-{region}"
    }

    r = requests.post(YOUTUBE_API_URL, json=payload, headers=headers)
    r.raise_for_status()
    data = r.json()

    videos = []
    sections = (
        data.get("contents", {})
            .get("twoColumnSearchResultsRenderer", {})
            .get("primaryContents", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
    )

    for section in sections:
        items = section.get("itemSectionRenderer", {}).get("contents", [])
        for item in items:
            vd = item.get("videoRenderer")
            if not vd:
                continue

            title = vd["title"]["runs"][0]["text"]
            vid = vd.get("videoId", "")
            owner_runs = vd.get("ownerText", {}).get("runs", [{}])
            author = owner_runs[0].get("text", "")
            nav = owner_runs[0].get("navigationEndpoint", {}).get("browseEndpoint", {})
            author_id = nav.get("browseId", "")
            author_url = nav.get("canonicalBaseUrl", "")
            author_badges = vd.get("ownerBadges", [])
            author_verified = any(
                b.get("metadataBadgeRenderer", {}).get("style") == "BADGE_STYLE_TYPE_VERIFIED"
                for b in author_badges
            )
            author_thumbs = (
                vd.get("channelThumbnailSupportedRenderers", {})
                  .get("channelThumbnailWithLinkRenderer", {})
                  .get("thumbnail", {})
                  .get("thumbnails", [])
            )
            for thumb in author_thumbs:
                if thumb.get('url'):
                    thumb['url'] = f"/ggpht{urllib.parse.urlparse(thumb['url']).path}"
            thumbs = vd.get("thumbnail", {}).get("thumbnails", [])
            desc = vd.get("descriptionSnippet", {}).get("runs", [{}])[0].get("text", "")
            view_text = vd.get("viewCountText", {}).get("simpleText", "")
            view_count = parse_view_count(view_text)
            published = vd.get("publishedTimeText", {}).get("simpleText", "")
            live = any(
                "LIVE" in b.get("metadataBadgeRenderer", {}).get("label", "").upper()
                for b in vd.get("badges", [])
            )
            length_obj, length_sec = extract_length_text_and_seconds(vd)

            videos.append({
                "type": "video",
                "title": title,
                "videoId": vid,
                "author": author,
                "authorId": author_id,
                "authorUrl": author_url,
                "authorVerified": author_verified,
                "authorThumbnails": author_thumbs,
                "videoThumbnails": thumbs,
                "description": desc,
                "viewCount": view_count,
                "viewCountText": view_text,
                "publishedText": published,
                "lengthText": length_obj,
                "lengthSeconds": length_sec,
                "liveNow": live,
            })

            if len(videos) >= max_results:
                break
        if len(videos) >= max_results:
            break

    return videos

def innertube_trending(trending_type=None, region="US", max_results=50):
    tkey = trending_type.lower() if trending_type else ""
    params = TRENDING_PARAMS.get(tkey, "")

    payload = {
        "context": CLIENT_CONTEXT,
        "browseId": "FEtrending",
    }
    if params:
        payload["params"] = params

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": f"en-{region}"
    }

    resp = requests.post(YOUTUBE_API_BROWSE_URL, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    try:
        section_list = (
            data.get("contents", {})
                .get("twoColumnBrowseResultsRenderer", {})
                .get("tabs", [])[0]
                .get("tabRenderer", {})
                .get("content", {})
                .get("sectionListRenderer", {})
                .get("contents", [])
        )

        all_items = []
        for sec in section_list:
            items = sec.get("itemSectionRenderer", {}).get("contents", [])
            all_items.extend(items)

        videos_raw = extract_videos_from_items(all_items)
        videos_raw = deduplicate_videos(videos_raw)[:max_results]

        def parse_video(vd):
            title = vd.get("title", {}).get("runs", [{}])[0].get("text", "")
            vid = vd.get("videoId", "")
            author = vd.get("ownerText", {}).get("runs", [{}])[0].get("text", "")
            thumbs = vd.get("thumbnail", {}).get("thumbnails", [])
            view_text = vd.get("viewCountText", {}).get("simpleText", "")
            published = vd.get("publishedTimeText", {}).get("simpleText", "")
            length_obj, length_sec = extract_length_text_and_seconds(vd)
            return {
                "title": title,
                "videoId": vid,
                "author": author,
                "videoThumbnails": thumbs,
                "viewCountText": view_text,
                "publishedText": published,
                "lengthText": length_obj,
                "lengthSeconds": length_sec
            }

        return [parse_video(v) for v in videos_raw]

    except Exception:
        return []

def parse_sub_count(text):
    match = re.match(r"([\d\.]+)([MK]?)", text)
    if not match:
        return 0
    num, suffix = match.groups()
    num = float(num)
    if suffix == "M":
        return int(num * 1_000_000)
    elif suffix == "K":
        return int(num * 1_000)
    return int(num)

def innertube_browse(browse_id, max_videos=30):
    payload = {
        "context": CLIENT_CONTEXT,
        "browseId": browse_id
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    r = requests.post(YOUTUBE_API_BROWSE_URL, json=payload, headers=headers)
    r.raise_for_status()
    data = r.json()

    channel_metadata = {
        "title": "Unknown Channel",
        "description": "",
        "subscriberCountText": "No subscribers",
        "sub_count": 0,
        "thumbnails": []
    }

    metadata_renderer = data.get('metadata', {}).get('channelMetadataRenderer', {})
    if metadata_renderer:
        channel_metadata.update({
            "title": metadata_renderer.get('title', channel_metadata['title']),
            "description": metadata_renderer.get('description', channel_metadata['description']),
        })
        if 'avatar' in metadata_renderer:
            thumbnails = metadata_renderer['avatar'].get('thumbnails', [])
            for thumb in thumbnails:
                if thumb.get('url'):
                    thumb['url'] = f"/ggpht{urllib.parse.urlparse(thumb['url']).path}"
            channel_metadata['thumbnails'] = thumbnails

    header = data.get('header', {}).get('c4TabbedHeaderRenderer', {})
    if header:
        subscriber_text = (
            header.get('subscriberCountText', {}).get('simpleText') or
            (header.get('subscriberCountText', {}).get('runs', [{}])[0].get('text'))
        )
        if subscriber_text:
            channel_metadata['subscriberCountText'] = subscriber_text
            channel_metadata['sub_count'] = parse_sub_count(subscriber_text)

        channel_metadata.update({
            "title": header.get('title', channel_metadata['title']),
        })
        if 'avatar' in header:
            thumbnails = header['avatar'].get('thumbnails', [])
            for thumb in thumbnails:
                if thumb.get('url'):
                    thumb['url'] = f"/ggpht{urllib.parse.urlparse(thumb['url']).path}"
            channel_metadata['thumbnails'] = thumbnails

    legacy_header = data.get('header', {}).get('pageHeaderRenderer', {})
    if legacy_header:
        channel_metadata.update({
            "title": legacy_header.get('pageTitle', channel_metadata['title'])
        })
        metadata_rows = legacy_header.get('content', {}) \
            .get('pageHeaderViewModel', {}) \
            .get('metadata', {}) \
            .get('contentMetadataViewModel', {}) \
            .get('metadataRows', [])

        for row in metadata_rows:
            parts = row.get('metadataParts', [])
            for part in parts:
                text = part.get('text', {}).get('content', '')
                if 'subscribers' in text.lower():
                    channel_metadata['subscriberCountText'] = text
                    channel_metadata['sub_count'] = parse_sub_count(text)
                    break
            if channel_metadata['sub_count'] > 0:
                break

    videos = ChannelVideos(Client(), browse_id).next(max_videos)
    videos_data = []

    for video in videos:
        thumb = video.thumbnails
        if hasattr(thumb, '__dict__'):
            thumb = vars(thumb)

        best_thumb = (
            thumb.get("default") or
            thumb.get("medium") or
            thumb.get("high") or
            thumb.get("standard") or
            thumb.get("maxres")
        )

        videos_data.append({
            "title": video.title,
            "videoId": video.id,
            "thumbnails": [{
                "url": best_thumb,
                "width": thumb.get("width", ""),
                "height": thumb.get("height", "")
            }],
            "lengthText": video.duration,
            "viewCountText": video.view_count
        })

    return {
        "metadata": channel_metadata,
        "videos": videos_data
    }
