from flask import Flask, request, Response, render_template_string
import xml.etree.ElementTree as ET
from xml.dom import minidom
from urllib.parse import parse_qs
import json
from innertube import (
    innertube_search,
    innertube_trending,
    innertube_browse,
#    innertube_comments,
    CLIENT_CONTEXT,
    YOUTUBE_API_URL,
    YOUTUBE_API_BROWSE_URL,
    VideoCompact,
    ChannelVideos,
    Thumbnails,
    parse_view_count
)
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

NS_ATOM = "http://www.w3.org/2005/Atom"
NS_OPENSEARCH = "http://a9.com/-/spec/opensearch/1.1/"
NS_YT = "http://gdata.youtube.com/schemas/2007"
NS_MEDIA = "http://search.yahoo.com/mrss/"

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
    rough_string = ET.tostring(root, "utf-8")
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

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

@app.route("/feeds/api/<path:path>", methods=["GET"])
def handle_gdata_request(path):
    params = request.args
    version = params.get("v", "2.1")
    fields = params.get("fields", "")
    max_results = int(params.get("max-results", 100))
    start_index = int(params.get("start-index", 1))

    if path.startswith("channelstandardfeeds/most_subscribed"):
        return handle_most_subscribed(max_results, start_index, fields, version)
    elif path.startswith("videos"):
        return handle_videos(params, max_results, start_index, fields, version)
    elif path.startswith("users/"):
        return handle_user_uploads(path, params, max_results, start_index, fields, version)
    elif path.startswith("playlists/"):
        return handle_playlists(path, params, max_results, start_index, fields, version)
    elif path.startswith("videos/") and path.endswith("/responses"):
        return handle_video_comments(path, params, max_results, start_index, fields, version)
    elif path.startswith("standardfeeds/most_popular"):
        return handle_most_popular(max_results, start_index, fields, version)
    else:
        return Response("Route not supported", status=404, mimetype="text/html")

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

def handle_videos(params, max_results, start_index, fields, version):
    query = params.get("q", "")
    videos = innertube_search(query, max_results=max_results) if query else innertube_trending(max_results=max_results)
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
        description = ET.SubElement(media_group, f"{{{NS_MEDIA}}}description")
        description.text = item.get("description", "")
        statistics = ET.SubElement(entry, f"{{{NS_YT}}}statistics")
        view_count = ET.SubElement(statistics, "viewCount")
        view_count.text = str(item.get("viewCount", 0))

    return Response(
        create_xml_response(root),
        mimetype="application/atom+xml"
    )

def handle_user_uploads(path, params, max_results, start_index, fields, version):
    user_id = path.split("/")[1]
    channel_data = innertube_browse(user_id, max_videos=max_results)
    root = ET.Element("feed", xmlns=NS_ATOM)
    root.set("xmlns:openSearch", NS_OPENSEARCH)
    root.set("xmlns:yt", NS_YT)
    root.set("xmlns:media", NS_MEDIA)
    total_results = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}totalResults")
    total_results.text = str(len(channel_data["videos"]))
    start_index_elem = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}startIndex")
    start_index_elem.text = str(start_index)
    items_per_page = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}itemsPerPage")
    items_per_page.text = str(max_results)

    for video in channel_data["videos"][start_index-1:start_index-1+max_results]:
        entry = ET.SubElement(root, "entry")
        title = ET.SubElement(entry, "title")
        title.text = video.get("title", "")
        video_id = ET.SubElement(entry, f"{{{NS_YT}}}videoId")
        video_id.text = video.get("videoId", "")
        media_group = ET.SubElement(entry, f"{{{NS_MEDIA}}}group")
        thumbnail = ET.SubElement(media_group, f"{{{NS_MEDIA}}}thumbnail")
        thumbnail_url = video.get("thumbnails", [{}])[0].get("url", "")
        thumbnail.set("url", thumbnail_url)
        statistics = ET.SubElement(entry, f"{{{NS_YT}}}statistics")
        view_count = ET.SubElement(statistics, "viewCount")
        view_count.text = video.get("viewCountText", "0")

    return Response(
        create_xml_response(root),
        mimetype="application/atom+xml"
    )

def handle_playlists(path, params, max_results, start_index, fields, version):
    playlist_id = path.split("/")[1]
    videos = innertube_search(f"playlist:{playlist_id}", max_results=max_results)
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

    return Response(
        create_xml_response(root),
        mimetype="application/atom+xml"
    )

def handle_video_comments(path, params, max_results, start_index, fields, version):
    video_id = path.split("/")[1]
    comments = innertube_comments(video_id, max_results=max_results)
    root = ET.Element("feed", xmlns=NS_ATOM)
    root.set("xmlns:openSearch", NS_OPENSEARCH)
    root.set("xmlns:yt", NS_YT)
    root.set("xmlns:media", NS_MEDIA)
    total_results = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}totalResults")
    total_results.text = str(len(comments))
    start_index_elem = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}startIndex")
    start_index_elem.text = str(start_index)
    items_per_page = ET.SubElement(root, f"{{{NS_OPENSEARCH}}}itemsPerPage")
    items_per_page.text = str(max_results)

    for comment in comments[start_index-1:start_index-1+max_results]:
        entry = ET.SubElement(root, "entry")
        title = ET.SubElement(entry, "title")
        title.text = f"Comment by {comment.get('author', 'Unknown')}"
        content = ET.SubElement(entry, "content")
        content.text = comment.get("text", "")
        author = ET.SubElement(entry, f"{{{NS_ATOM}}}author")
        name = ET.SubElement(author, f"{{{NS_ATOM}}}name")
        name.text = comment.get("author", "Unknown")

    return Response(
        create_xml_response(root),
        mimetype="application/atom+xml"
    )

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

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5006)
