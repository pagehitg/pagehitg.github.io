
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

API_URL = "https://www.googleapis.com/youtube/v3/"
CHANNEL_HANDLE = "@hitgs_offcl"
OUTPUT_FILE = Path("videos.js")

# Firebase에서 등록된 팬튜브 채널 목록 가져오기
def load_fan_channels():
    import firebase_admin
    from firebase_admin import credentials, firestore

    service_account = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

    if not service_account:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT is missing")

    if not firebase_admin._apps:
        credential = credentials.Certificate(json.loads(service_account))
        firebase_admin.initialize_app(credential)

    db = firestore.client()
    channels = []

    for document in db.collection("fanChannels").stream():
        data = document.to_dict()

        if data.get("enabled", True) and data.get("url"):
            channels.append(data["url"])

    return channels

def youtube_api(endpoint, **params):
    params["key"] = os.environ["YOUTUBE_API_KEY"]

    url = API_URL + endpoint + "?" + urllib.parse.urlencode(params)

    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


# 팬튜브 채널의 영상 수집
def collect_fan_videos(channel_url):
    parsed = urllib.parse.urlparse(channel_url)
    path = urllib.parse.unquote(parsed.path).strip("/")

    if path.startswith("@"):
        response = youtube_api(
            "channels",
            part="snippet,contentDetails",
            forHandle=path
        )
    elif path.startswith("channel/"):
        response = youtube_api(
            "channels",
            part="snippet,contentDetails",
            id=path.split("/", 1)[1]
        )
    elif path.startswith("user/"):
        response = youtube_api(
            "channels",
            part="snippet,contentDetails",
            forUsername=path.split("/", 1)[1]
        )
    else:
        print(f"Unsupported channel URL: {channel_url}")
        return []

    channels = response.get("items", [])

    if not channels:
        print(f"Fan channel not found: {channel_url}")
        return []

    channel = channels[0]
    channel_name = channel["snippet"]["title"]
    uploads_playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]

    videos = []
    page_token = None

    while True:
        params = {
            "part": "snippet",
            "playlistId": uploads_playlist,
            "maxResults": 50
        }

        if page_token:
            params["pageToken"] = page_token

        response = youtube_api("playlistItems", **params)

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId")
            title = snippet.get("title", "")
            date = snippet.get("publishedAt", "")[:10]

            if not video_id or not re.fullmatch(
                r"[A-Za-z0-9_-]{11}", video_id
            ):
                continue

            if title in ("Private video", "Deleted video") or not date:
                continue

            videos.append({
                "title": title,
                "url": "https://www.youtube.com/watch?v=" + video_id,
                "year": date[:4],
                "category": "FANTUBE",
                "member": "ALL",
                "channel": channel_name,
                "date": date,
                "type": "VIDEO",
                "duration": ""
            })

        page_token = response.get("nextPageToken")

        if not page_token:
            break

    print(f"Fan channel {channel_name}: {len(videos)} videos")
    return videos
def main():
    if not os.environ.get("YOUTUBE_API_KEY"):
        raise SystemExit("YOUTUBE_API_KEY is missing")

    fan_channels = load_fan_channels()
    print(f"Registered fan channels: {len(fan_channels)}")


    channel_data = youtube_api(
        "channels",
        part="snippet,contentDetails",
        forHandle=CHANNEL_HANDLE
    )

    channels = channel_data.get("items", [])

    if len(channels) != 1:
        raise SystemExit("Official channel not found")

    channel = channels[0]
    channel_name = channel["snippet"]["title"]

    uploads_playlist = channel["contentDetails"][
        "relatedPlaylists"
    ]["uploads"]

    official_videos = []
    page_token = None

    while True:
        params = {
            "part": "snippet",
            "playlistId": uploads_playlist,
            "maxResults": 50
        }

        if page_token:
            params["pageToken"] = page_token

        response = youtube_api("playlistItems", **params)

        for item in response.get("items", []):
            snippet = item.get("snippet", {})

            video_id = snippet.get(
                "resourceId", {}
            ).get("videoId")

            title = snippet.get("title", "")
            date = snippet.get("publishedAt", "")[:10]

            if not video_id or not re.fullmatch(
                r"[A-Za-z0-9_-]{11}", video_id
            ):
                continue

            if title in ("Private video", "Deleted video"):
                continue

            if not date:
                continue

            official_videos.append({
                "title": title,
                "url": (
                    "https://www.youtube.com/watch?v="
                    + video_id
                ),
                "year": date[:4],
                "category": "OFFICIAL",
                "member": "ALL",
                "channel": channel_name,
                "date": date
            })

        page_token = response.get("nextPageToken")

        if not page_token:
            break

    # 영상 길이 및 제목을 기준으로 SHORTS 후보 분류
    for start in range(0, len(official_videos), 50):
        batch = official_videos[start:start + 50]

        video_ids = [
            video["url"].split("v=")[-1]
            for video in batch
        ]

        response = youtube_api(
            "videos",
            part="contentDetails,liveStreamingDetails",
            id=",".join(video_ids)
        )

        durations = {
            item["id"]: item.get("contentDetails", {}).get("duration", "")
            for item in response.get("items", [])
        }

        live_video_ids = {
            item["id"]
            for item in response.get("items", [])
            if item.get("liveStreamingDetails", {}).get(
                "actualEndTime"
            )
        }

        for video in batch:
            video_id = video["url"].split("v=")[-1]
            duration = durations.get(video_id, "")
            title = video["title"]

            match = re.fullmatch(
                r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
                duration
            )

            seconds = None

            if match:
                hours, minutes, secs = match.groups()
                seconds = (
                    int(hours or 0) * 3600
                    + int(minutes or 0) * 60
                    + int(secs or 0)
                )

            # 영상 길이를 표시용으로 저장
            if seconds is not None:
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                secs = seconds % 60

                if hours > 0:
                    video["duration"] = f"{hours}:{minutes:02d}:{secs:02d}"
                else:
                    video["duration"] = f"{minutes}:{secs:02d}"
            else:
                video["duration"] = ""
            has_shorts_tag = bool(
                re.search(r"#?shorts\b", title, re.I)
            )

            excluded = bool(
                re.search(
                    r"\b(MV|M/V|TEASER|BEHIND|REACTION)\b",
                    title,
                    re.I
                )
            )

            video["type"] = (
                "SHORTS"
                if (
                    has_shorts_tag
                    or (seconds is not None and seconds <= 180 and not excluded)
                )
                else "VIDEO"
            )
            
            video["isLive"] = video_id in live_video_ids

    # 공식 유튜브 채널의 재생목록 수집
    official_playlists = []
    playlist_page_token = None

    while True:
        params = {
            "part": "snippet,contentDetails",
            "channelId": channel["id"],
            "maxResults": 50
        }

        if playlist_page_token:
            params["pageToken"] = playlist_page_token

        playlist_response = youtube_api("playlists", **params)

        for item in playlist_response.get("items", []):
            snippet = item.get("snippet", {})
            playlist_id = item.get("id", "")

            if not playlist_id:
                continue

            official_playlists.append({
                "title": snippet.get("title", ""),
                "url": "https://www.youtube.com/playlist?list=" + playlist_id,
                "thumbnail": snippet.get("thumbnails", {}).get(
                    "high", {}
                ).get("url", ""),
                "videoCount": item.get(
                    "contentDetails", {}
                ).get("itemCount", 0),
                "date": snippet.get("publishedAt", "")[:10]
            })

        playlist_page_token = playlist_response.get("nextPageToken")

        if not playlist_page_token:
            break

    # 기존에 수동 등록한 다른 카테고리 영상 유지
    existing_videos = []

    if OUTPUT_FILE.exists():
        old_content = OUTPUT_FILE.read_text(
            encoding="utf-8"
        )

        match = re.search(
            r"const\s+videos\s*=\s*(\[.*?\])\s*;",
            old_content,
            re.S
        )

        if not match:
            raise SystemExit(
                "Cannot parse existing videos.js"
            )

        try:
            existing_videos = json.loads(match.group(1))
        except json.JSONDecodeError:
            print("Existing videos.js is not valid JSON; skipping legacy entries.")
            existing_videos = []

    other_videos = [
        video for video in existing_videos
        if isinstance(video, dict)
        and str(
            video.get("category", "")
        ).upper() != "OFFICIAL"
        and video.get("url") != (
            "https://www.youtube.com/watch?v=VIDEO_ID"
        )
    ]

    
    # Firebase에 등록된 팬튜브 채널 영상 수집
    fan_videos = []

    for channel_url in fan_channels:
        try:
            collected = collect_fan_videos(channel_url)
            fan_videos.extend(collected)
        except Exception as error:
            print(f"Failed to collect fan channel {channel_url}: {error}")

    print(f"Total fan videos: {len(fan_videos)}")

    # 자동 수집한 팬튜브 영상으로 기존 팬튜브 목록 갱신
    # 수집 실패 시 기존 영상은 유지
    if fan_channels and fan_videos:
        other_videos = [
            video for video in other_videos
            if str(video.get("category", "")).upper() != "FANTUBE"
        ]

    # URL 기준 중복 제거
    unique_videos = {}

    for video in official_videos + fan_videos + other_videos:
        url = video.get("url")

        if url and url not in unique_videos:
            unique_videos[url] = video

    # 최신순 정렬
    sorted_videos = sorted(
        unique_videos.values(),
        key=lambda video: video.get("date", ""),
        reverse=True
    )

    new_content = (
        "const videos = "
        + json.dumps(
            sorted_videos,
            ensure_ascii=False,
            indent=2
        )
        + ";\n"
    )

    OUTPUT_FILE.write_text(
        new_content,
        encoding="utf-8"
    )
    
    # 재생목록을 별도 JS 파일에 저장
    playlist_content = (
        "const playlists = "
        + json.dumps(
            official_playlists,
            ensure_ascii=False,
            indent=2
        )
        + ";\n"
    )

    Path("playlists.js").write_text(
        playlist_content,
        encoding="utf-8"
    )


    print(
        f"Official videos: {len(official_videos)}"
    )
    print(
        f"Total archive videos: {len(sorted_videos)}"
    )


if __name__ == "__main__":
    main()
