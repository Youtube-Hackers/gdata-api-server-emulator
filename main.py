from flask import Flask, request, Response, render_template_string
import xml.etree.ElementTree as ET
from xml.dom import minidom
from urllib.parse import parse_qs
import json
from innertube import (
    innertube_search,
    innertube_trending,
    innertube_browse,
    innertube_comments,
    CLIENT_CONTEXT,
    YOUTUBE_API_URL,
    YOUTUBE_API_BROWSE_URL,
    VideoCompact,
    ChannelVideos,
    Thumbnails,
    parse_view_count
)
from flask_cors import CORS
from streamer import GetVideo
import streamer

app = Flask(__name__)
CORS(app)
streamer = GetVideo()

NS_ATOM = "http://www.w3.org/2005/Atom"
NS_OPENSEARCH = "http://a9.com/-/spec/opensearch/1.1/"
NS_YT = "http://gdata.youtube.com/schemas/2007"
NS_MEDIA = "http://search.yahoo.com/mrss/"

for prefix, uri in [('', NS_ATOM), ('openSearch', NS_OPENSEARCH), ('yt', NS_YT), ('media', NS_MEDIA)]:
    ET.register_namespace(prefix, uri)


ERROR_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
  <meta charset="utf-8">
  <meta name="viewport" content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error {{ code }} ({{ title }})!!1</title>
  <style>
{% raw %}
    *{margin:0;padding:0}html,code{font:15px/22px arial,sans-serif}html{background:#fff;color:#222;padding:15px}body{margin:7% auto 0;max-width:390px;min-height:180px;padding:30px 0 15px}* > body{background:url(//www.google.com/images/errors/robot.png) 100% 5px no-repeat;padding-right:205px}p{margin:11px 0 22px;overflow:hidden}ins{color:#777;text-decoration:none}a img{border:0}@media screen and (max-width:772px){body{background:none;margin-top:0;max-width:none;padding-right:0}}#logo{background:url(//www.google.com/images/branding/googlelogo/1x/googlelogo_color_150x54dp.png) no-repeat;margin-left:-5px}@media only screen and (min-resolution:192dpi){#logo{background:url(//www.google.com/images/branding/googlelogo/2x/googlelogo_color_150x54dp.png) no-repeat 0% 0%/100% 100%;-moz-border-image:url(//www.google.com/images/branding/googlelogo/2x/googlelogo_color_150x54dp.png) 0}}@media only screen and (-webkit-min-device-pixel-ratio:2){#logo{background:url(//www.google.com/images/branding/googlelogo/2x/googlelogo_color_150x54dp.png) no-repeat;-webkit-background-size:100% 100%}}#logo{display:inline-block;height:54px;width:150px}
{% endraw %}
  </style>
  <a href="//www.google.com/"><span id="logo" aria-label="Google"></span></a>
  <p><b>{{ code }}.</b> <ins>That’s an error.</ins>
  <p>The requested URL <code>{{ url }}</code> was not found on this server.  <ins>That’s all we know.</ins>
</html>
"""

def create_xml_response(root):
    rough = ET.tostring(root, "utf-8")
    dom = minidom.parseString(rough)
    return dom.toprettyxml(indent="  ")

def parse_fields(fields):
    if not fields:
        return None
    return fields.split(",")

@app.errorhandler(404)
def not_found(error):
    return render_template_string(
        ERROR_TEMPLATE,
        code=404,
        title="Not Found",
        url=request.path
    ), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template_string(
        ERROR_TEMPLATE,
        code=500,
        title="Internal Server Error",
        url=request.path
    ), 500

def build_feed(videos, total, start_index, max_results):
    root = ET.Element(f"{{{NS_ATOM}}}feed")
    ET.SubElement(root, f"{{{NS_OPENSEARCH}}}totalResults").text = str(total)
    ET.SubElement(root, f"{{{NS_OPENSEARCH}}}startIndex").text = str(start_index)
    ET.SubElement(root, f"{{{NS_OPENSEARCH}}}itemsPerPage").text = str(max_results)
    return root

def add_video_entry(root, item):
    vid = item.get("videoId")
    entry = ET.SubElement(root, f"{{{NS_ATOM}}}entry")
    ET.SubElement(entry, f"{{{NS_ATOM}}}id").text = f"http://gdata.youtube.com/feeds/api/videos/{vid}"
    ET.SubElement(entry, f"{{{NS_ATOM}}}published").text = item.get("published", "")
    ET.SubElement(entry, f"{{{NS_ATOM}}}updated").text = item.get("published", "")
    ET.SubElement(entry, f"{{{NS_ATOM}}}title").text = item.get("title", "")
    ET.SubElement(entry, f"{{{NS_ATOM}}}content").text = item.get("description", "")
    author = ET.SubElement(entry, f"{{{NS_ATOM}}}author")
    ET.SubElement(author, f"{{{NS_ATOM}}}name").text = item.get("author", "")
    ET.SubElement(author, f"{{{NS_ATOM}}}uri").text = f"http://gdata.youtube.com/feeds/api/users/{item.get('authorId', '')}"
    ET.SubElement(entry, f"{{{NS_ATOM}}}link", {
        "rel": "alternate",
        "type": "text/html",
        "href": f"https://www.youtube.com/watch?v={vid}"
    })
    media = ET.SubElement(entry, f"{{{NS_MEDIA}}}group")
    ET.SubElement(media, f"{{{NS_MEDIA}}}title").text = item.get("title", "")
    ET.SubElement(media, f"{{{NS_MEDIA}}}description").text = item.get("description", "")
    ET.SubElement(media, f"{{{NS_MEDIA}}}player", {"url": f"https://www.youtube.com/watch?v={vid}"})
    thumb = item.get("videoThumbnails", [{}])[0].get("url", "")
    ET.SubElement(media, f"{{{NS_MEDIA}}}thumbnail", {"url": thumb})
    ET.SubElement(entry, f"{{{NS_YT}}}statistics", {
        "viewCount": str(item.get("viewCount", 0)),
        "favoriteCount": str(item.get("favoriteCount", 0))
    })



@app.route("/feeds/api/<path:path>")
def handle_gdata_request(path):
    params = request.args
    version = params.get("v", "2")
    fields = params.get("fields", "")
    max_results = int(params.get("max-results", 100))
    start_index = int(params.get("start-index", 1))

    if path.startswith("videos/") and len(path.split("/")) == 2:
        video_id = path.split("/")[1]
        return handle_video_detail(video_id)
    elif path.startswith("videos/") and path.endswith("/responses"):
        return handle_video_comments(path, max_results, start_index)
    elif path.startswith("videos/") and path.endswith("/comments"):
        return handle_video_comments(path, max_results, start_index)
    elif path.startswith("standardfeeds/most_popular"):
        return handle_videos(params, max_results, start_index)
    elif path.startswith("channelstandardfeeds/most_subscribed"):
        return handle_channels(max_results, start_index)
    elif path.startswith("videos"):
        return handle_videos(params, max_results, start_index)
    elif path.startswith("users/"):
        return handle_user_uploads(path, max_results, start_index)
    elif path.startswith("playlists/"):
        return handle_playlists(path, max_results, start_index)
    else:
        return render_template_string(ERROR_TEMPLATE, code=404, title="Not Found", url=request.path), 404

def handle_most_subscribed(max_results, start_index, fields, version):
    videos = innertube_search("channel", max_results=max_results)
    root = ET.Element("feed", xmlns=NS_ATOM)
    root.set("xmlns:openSearch", NS_OPENSEARCH)
    root.set("xmlns:yt", NS_YT)
    root.set("xmlns:media", NS_MEDIA)
    total_results = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}totalResults")
    total_results.text = str(len(videos))
    start_index_elem = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}startIndex")
    start_index_elem.text = str(start_index)
    items_per_page = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}itemsPerPage")
    items_per_page.text = str(max_results)

    for item in videos[start_index-1:start_index-1+max_results]:
        entry = ET.SubElement(root, "entry")
        title = ET.SubElement(entry, "title")
        title.text = item.get("author", "Unknown Channel")
        channel_id = ET.SubElement(entry, f"{{{NS_YT}}}channelId")
        channel_id.text = item.get("authorId", "")
        statistics = ET.SubElement(entry, f"{{{NS_YT}}}channelStatistics")
        subscriber_count = ET.SubElement(statistics, "subscriberCount")
        subscriber_count.text = item.get("subscriberCountText", "0")
        media_group = ET.SubElement(entry, f"{{{NS_MEDIA}}}group")
        thumbnail = ET.SubElement(media_group, f"{{{NS_MEDIA}}}thumbnail")
        thumbnail_url = item.get("authorThumbnails", [{}])[0].get("url", "")
        thumbnail.set("url", thumbnail_url)

    return Response(
        create_xml_response(root),
        mimetype="application/atom+xml"
    )

def handle_videos(params, max_results, start_index):
    query = params.get("q")
    videos = innertube_search(query, max_results=max_results) if query else innertube_trending(max_results=max_results)
    root = build_feed(videos, len(videos), start_index, max_results)
    for item in videos[start_index-1:start_index-1+max_results]:
        add_video_entry(root, item)
    return Response(create_xml_response(root), mimetype="application/atom+xml; charset=UTF-8")

def handle_video_detail(video_id):
    try:
        data = streamer.fetch_video_data(video_id)
    except Exception as e:
        print(f"fetch_video_data error: {e}")
        return render_template_string(ERROR_TEMPLATE, code=500, title="Video Fetch Error", url=request.path), 500

    details = data.get("videoDetails", {})
    if not details:
        return render_template_string(ERROR_TEMPLATE, code=404, title="Video Not Found", url=request.path), 404

    microformat = data.get("microformat", {}).get("playerMicroformatRenderer", {})

    ET.register_namespace('', NS_ATOM)
    ET.register_namespace('media', NS_MEDIA)
    ET.register_namespace('yt', NS_YT)

    root = ET.Element("entry")
    ET.SubElement(root, f"{{{NS_ATOM}}}id").text = f"http://gdata.youtube.com/feeds/api/videos/{video_id}"
    ET.SubElement(root, f"{{{NS_ATOM}}}published").text = microformat.get("publishDate", "")
    ET.SubElement(root, f"{{{NS_ATOM}}}updated").text = microformat.get("uploadDate", "")
    ET.SubElement(root, f"{{{NS_ATOM}}}title").text = details.get("title", "")
    ET.SubElement(root, f"{{{NS_ATOM}}}content").text = details.get("shortDescription", "")

    author = ET.SubElement(root, f"{{{NS_ATOM}}}author")
    ET.SubElement(author, f"{{{NS_ATOM}}}name").text = details.get("author", "")
    ET.SubElement(author, f"{{{NS_ATOM}}}uri").text = f"http://gdata.youtube.com/feeds/api/users/{details.get('channelId', '')}"

    ET.SubElement(root, f"{{{NS_ATOM}}}link", {
        "rel": "alternate",
        "type": "text/html",
        "href": f"https://www.youtube.com/watch?v={video_id}"
    })

    media = ET.SubElement(root, f"{{{NS_MEDIA}}}group")
    ET.SubElement(media, f"{{{NS_MEDIA}}}title").text = details.get("title", "")
    ET.SubElement(media, f"{{{NS_MEDIA}}}description").text = details.get("shortDescription", "")
    ET.SubElement(media, f"{{{NS_MEDIA}}}player", {"url": f"https://www.youtube.com/watch?v={video_id}"})

    thumbnail_list = details.get("thumbnail", {}).get("thumbnails", [])
    if thumbnail_list:
        ET.SubElement(media, f"{{{NS_MEDIA}}}thumbnail", {"url": thumbnail_list[0].get("url", "")})

    ET.SubElement(media, f"{{{NS_YT}}}duration", {
        "seconds": str(details.get("lengthSeconds", 0))
    })

    ET.SubElement(root, f"{{{NS_YT}}}videoId").text = video_id
    ET.SubElement(root, f"{{{NS_YT}}}statistics", {
        "viewCount": str(details.get("viewCount", 0)),
        "favoriteCount": "0"
    })

    return Response(create_xml_response(root), mimetype="application/atom+xml; charset=UTF-8")

def handle_user_uploads(path, max_results, start_index):
    user = path.split("/")[1]
    data = innertube_browse(user, max_videos=max_results)
    videos = data["videos"]
    root = build_feed(videos, len(videos), start_index, max_results)
    for item in videos[start_index-1:start_index-1+max_results]:
        add_video_entry(root, item)
    return Response(create_xml_response(root), mimetype="application/atom+xml; charset=UTF-8")

def handle_playlists(path, max_results, start_index):
    pid = path.split("/")[1]
    videos = innertube_search(f"playlist:{pid}", max_results=max_results)
    root = build_feed(videos, len(videos), start_index, max_results)
    for item in videos[start_index-1:start_index-1+max_results]:
        add_video_entry(root, item)
    return Response(create_xml_response(root), mimetype="application/atom+xml; charset=UTF-8")

def handle_video_comments(path, max_results, start_index):
    vid = path.split("/")[1]
    comments = innertube_comments(vid, max_results=max_results)
    root = build_feed(comments, len(comments), start_index, max_results)

    for cm in comments[start_index-1:start_index-1+max_results]:
        entry = ET.SubElement(root, f"{{{NS_ATOM}}}entry")
        ET.SubElement(entry, f"{{{NS_ATOM}}}title").text = f"Comment by {cm.get('author', '')}"
        ET.SubElement(entry, f"{{{NS_ATOM}}}content").text = cm.get("text", "")
        author = ET.SubElement(entry, f"{{{NS_ATOM}}}author")
        ET.SubElement(author, f"{{{NS_ATOM}}}name").text = cm.get("author", "")
    return Response(create_xml_response(root), mimetype="application/atom+xml; charset=UTF-8")

def handle_most_popular(max_results, start_index, fields, version):
    videos = innertube_trending(max_results=max_results)
    root = ET.Element("feed", xmlns=NS_ATOM)
    root.set("xmlns:openSearch", NS_OPENSEARCH)
    root.set("xmlns:yt", NS_YT)
    root.set("xmlns:media", NS_MEDIA)
    total_results = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}totalResults")
    total_results.text = str(len(videos))
    start_index_elem = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}startIndex")
    start_index_elem.text = str(start_index)
    items_per_page = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}itemsPerPage")
    items_per_page.text = str(max_results)

    for item in videos[start_index-1:start_index-1+max_results]:
        entry = ET.SubElement(root, "entry")
        title = ET.SubElement(entry, "title")
        title.text = item.get("title", "")
        video_id = ET.SubElement(entry, f"{{{NS_YT}}}videoId")
        video_id.text = item.get("videoId", "")
        media_group = ET.SubElement(entry, f"{{{NS_MEDIA}}}group")
        thumbnail = ET.SubElement(media_group, f"{{{NS_MEDIA}}}thumbnail")
        thumbnail_url = item.get("videoThumbnails", [{}])[0].get("url", "")
        thumbnail.set("url", thumbnail_url)
        statistics = ET.SubElement(entry, f"{{{NS_YT}}}statistics")
        view_count = ET.SubElement(statistics, "viewCount")
        view_count.text = item.get("viewCountText", "0")

    return Response(
        create_xml_response(root),
        mimetype="application/atom+xml"
    )

def handle_channels(max_results, start_index):
    channels = innertube_search("channel", max_results=max_results)
    root = ET.Element(f"{{{NS_ATOM}}}feed")
    ET.SubElement(root, f"{{{NS_OPENSEARCH}}}totalResults").text = str(len(channels))
    ET.SubElement(root, f"{{{NS_OPENSEARCH}}}startIndex").text = str(start_index)
    ET.SubElement(root, f"{{{NS_OPENSEARCH}}}itemsPerPage").text = str(max_results)

    for ch in channels[start_index-1:start_index-1+max_results]:
        entry = ET.SubElement(root, f"{{{NS_ATOM}}}entry")
        ET.SubElement(entry, f"{{{NS_ATOM}}}title").text = ch.get("author", "")
        ET.SubElement(entry, f"{{{NS_YT}}}channelId").text = ch.get("authorId", "")
        ET.SubElement(entry, f"{{{NS_YT}}}statistics", {"subscriberCount": ch.get("subscriberCountText", "0")})

        media = ET.SubElement(entry, f"{{{NS_MEDIA}}}group")
        thumb = ch.get("authorThumbnails", [{}])[0].get("url", "")
        ET.SubElement(media, f"{{{NS_MEDIA}}}thumbnail", {"url": thumb})
    return Response(create_xml_response(root), mimetype="application/atom+xml; charset=UTF-8")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5006)
