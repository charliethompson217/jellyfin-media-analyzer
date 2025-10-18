import requests
import json
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from config import JELLYFIN_URL, API_KEY, CACHE_FILE, PORT

app = Flask(__name__)
CORS(app)

def fetch_all_items(base_params):
    """Fetch all items with paging"""
    all_items = []
    start_index = 0
    limit = 500
    while True:
        params = base_params.copy()
        params['StartIndex'] = start_index
        params['Limit'] = limit
        try:
            resp = requests.get(f'{JELLYFIN_URL}/Items', params=params)
            resp.raise_for_status()
            result = resp.json()
            items = result['Items']
            all_items.extend(items)
            if len(items) < limit:
                break
            start_index += limit
        except Exception as e:
            raise Exception(f'Fetch failed: {str(e)}')
    return all_items

@app.route('/api/media')
def get_media():
    refresh = request.args.get('refresh', 'false').lower() == 'true'  # ?refresh=true to nuke cache
    if not refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                return jsonify(json.load(f))
        except Exception as e:
            return jsonify({'error': f'Cache read bombed: {str(e)}'}), 500

    # Grab user ID
    user_params = {'api_key': API_KEY}
    try:
        user_resp = requests.get(f'{JELLYFIN_URL}/Users', params=user_params)
        user_resp.raise_for_status()
        users = user_resp.json()
        if not users:
            return jsonify({'error': 'No users? Your Jellyfin\'s empty.'}), 500
        user_id = users[0]['Id']
    except Exception as e:
        return jsonify({'error': f'User grab bombed: {str(e)}'}), 500

    # Base fields for media details
    fields = 'MediaSources,MediaStreams,Path,SeriesName,SeasonName,IndexNumber'

    # Fetch all movies and episodes, forcing no collapse on boxsets
    direct_params = {
        'userId': user_id,
        'IncludeItemTypes': 'Movie,Episode',
        'Recursive': True,
        'Fields': fields,
        'CollapseBoxSetItems': 'false',
        'api_key': API_KEY
    }
    all_items = fetch_all_items(direct_params)

    data = []
    seen_paths = set()  # Dedup by path
    for item in all_items:
        if item.get('Type') == 'BoxSet':  # Skip any boxset that slips in
            continue
        if item.get('LocationType') != 'FileSystem':
            continue
        path = item.get('Path', 'Unknown')
        if path in seen_paths:
            continue
        seen_paths.add(path)

        ms = item.get('MediaSources', [{}])[0]
        container = ms.get('Container', 'Unknown')
        size_mb = ms.get('Size', 0) / (1024 * 1024) if ms.get('Size') else 0

        streams = item.get('MediaStreams', [])
        video = next((s for s in streams if s.get('Type') == 'Video'), {})
        video_codec = video.get('Codec', 'Unknown').upper()
        resolution = f"{video.get('Width', '?')}x{video.get('Height', '?')}"
        fps = round(video.get('RealFrameRate', 0), 2) if video.get('RealFrameRate') else 'Unknown'
        hdr = video.get('VideoRangeType', 'SDR')
        color_gamut = video.get('ColorPrimaries', 'Unknown')

        audio = [s for s in streams if s.get('Type') == 'Audio']
        audio_codec = ', '.join(set(a.get('Codec', 'Unknown').upper() for a in audio)) if audio else 'None'
        audio_channels = max((a.get('Channels', 0) for a in audio), default=0)
        audio_bitrate_kbps = sum(a.get('BitRate', 0) for a in audio) / 1000 if audio else 0
        audio_sample = audio[0].get('SampleRate', 'Unknown') if audio else 'None'
        audio_tracks = len(audio)

        video_bitrate_kbps = video.get('BitRate', 0) / 1000 if video.get('BitRate') else 0

        duration_ticks = item.get('RunTimeTicks', 0)
        duration_sec = duration_ticks / 10000000
        duration_min = duration_sec / 60 if duration_sec else 0

        scan_type = 'Progressive' if video.get('IsInterlaced') is False else 'Interlaced' if video.get('IsInterlaced') else 'Unknown'

        efficiency = size_mb / (duration_min / 60) if duration_min > 0 else 0  # MiB/hour

        item_type = item.get('Type', 'Unknown')
        # Treat 'Video' as 'Movie'
        if item_type == 'Video':
            item_type = 'Movie'

        data.append({
            'name': item.get('Name', 'Unknown'),
            'type': item_type,
            'series_name': item.get('SeriesName', '') if item_type == 'Episode' else '',
            'season_name': item.get('SeasonName', '') if item_type == 'Episode' else '',
            'episode_number': item.get('IndexNumber', None) if item_type == 'Episode' else None,
            'path': path,
            'container': container,
            'video_codec': video_codec,
            'video_bitrate_kbps': round(video_bitrate_kbps),
            'frame_rate': fps,
            'hdr_info': hdr,
            'color_gamut': color_gamut,
            'scan_type': scan_type,
            'audio_codec': audio_codec,
            'audio_bitrate_kbps': round(audio_bitrate_kbps),
            'audio_sample_rate': audio_sample,
            'audio_channels': audio_channels,
            'audio_track_count': audio_tracks,
            'resolution': resolution,
            'duration_min': round(duration_min, 2),
            'size_mb': round(size_mb, 2),
            'efficiency_mb_per_hour': round(efficiency, 2)
        })

    # Cache this for next time
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f'Cache write failed: {str(e)}')

    return jsonify(data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
