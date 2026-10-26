"""Normalize optional Jellyfin metadata without losing incomplete files."""
import hashlib
import math
from pathlib import PurePosixPath
from urllib.parse import quote


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return value
    return None


def text(value, default='Unknown'):
    return value if isinstance(value, str) and value else default


def rounded(value, digits=0):
    return round(value, digits) if value is not None else None


def download_url(path, roots):
    if not path or not isinstance(path, str):
        return None
    candidate = PurePosixPath(path)
    if not candidate.is_absolute() or '..' in candidate.parts:
        return None
    for root, prefix in sorted(roots, key=lambda pair: len(pair[0]), reverse=True):
        if not root or not PurePosixPath(root).is_absolute():
            continue
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if relative.parts:
            return prefix + quote(relative.as_posix(), safe='/')
    return None


def normalize_items(items, roots):
    data, seen = [], set()
    skipped = 0
    for item_index, item in enumerate(items):
        if not isinstance(item, dict):
            skipped += 1
            continue
        if item.get('Type') not in ('Movie', 'Episode', 'Video') or item.get('LocationType') != 'FileSystem':
            continue
        sources = item.get('MediaSources')
        if not isinstance(sources, list) or not sources:
            skipped += 1
            continue
        for source_index, source in enumerate(sources):
            if not isinstance(source, dict):
                skipped += 1
                continue
            path = text(source.get('Path'), None)
            source_id, item_id = text(source.get('Id'), ''), text(item.get('Id'), '')
            identity = ('path', path) if path else ('source', item_id or item_index, source_id or source_index)
            if identity in seen:
                continue
            seen.add(identity)
            streams = source.get('MediaStreams')
            streams = [s for s in streams if isinstance(s, dict)] if isinstance(streams, list) else []
            video = next((s for s in streams if s.get('Type') == 'Video'), {})
            audio = [s for s in streams if s.get('Type') == 'Audio']
            size_bytes = number(source.get('Size'))
            size_mib = size_bytes / 1024**2 if size_bytes is not None else None
            ticks = number(source.get('RunTimeTicks'))
            if ticks is None:
                ticks = number(item.get('RunTimeTicks'))
            seconds = ticks / 10_000_000 if ticks is not None else None
            minutes = seconds / 60 if seconds is not None else None
            video_bitrate = number(video.get('BitRate'))
            audio_bitrates = [number(a.get('BitRate')) for a in audio]
            total_audio_bitrate = sum(audio_bitrates) if audio and all(v is not None for v in audio_bitrates) else None
            channels = [v for a in audio if (v := number(a.get('Channels'))) is not None]
            fps = number(video.get('RealFrameRate')) or number(video.get('AverageFrameRate'))
            width, height = number(video.get('Width')), number(video.get('Height'))
            efficiency = size_mib / (seconds / 3600) if size_mib is not None and seconds else None
            interlaced = video.get('IsInterlaced')
            item_type = 'Movie' if item.get('Type') == 'Video' else item['Type']
            production_year = number(item.get('ProductionYear'))
            production_year = (
                int(production_year)
                if production_year is not None and production_year == int(production_year)
                and 1000 <= production_year <= 9999 else None
            )
            data.append({
                'id': hashlib.sha256(repr(identity).encode()).hexdigest(),
                'item_id': item_id, 'source_id': source_id, 'name': text(item.get('Name')),
                'metadata_title': text(item.get('Name'), None), 'production_year': production_year,
                'version_name': text(source.get('Name'), ''), 'type': item_type,
                'series_name': text(item.get('SeriesName'), '') if item_type == 'Episode' else '',
                'season_name': text(item.get('SeasonName'), '') if item_type == 'Episode' else '',
                'episode_number': number(item.get('IndexNumber')) if item_type == 'Episode' else None,
                'path': path, 'download_url': download_url(path, roots), 'container': text(source.get('Container')),
                'video_codec': text(video.get('Codec')).upper(),
                'video_bitrate_kbps': rounded(video_bitrate / 1000) if video_bitrate is not None else None,
                'frame_rate': rounded(fps, 2), 'hdr_info': text(video.get('VideoRangeType')),
                'color_gamut': text(video.get('ColorPrimaries')),
                'scan_type': 'Interlaced' if interlaced is True else 'Progressive' if interlaced is False else 'Unknown',
                'audio_codec': ', '.join(sorted({text(a.get('Codec')).upper() for a in audio})) if audio else 'None',
                'audio_bitrate_kbps': rounded(total_audio_bitrate / 1000) if total_audio_bitrate is not None else None,
                'audio_sample_rate': number(audio[0].get('SampleRate')) if audio else None,
                'audio_channels': max(channels, default=None), 'audio_track_count': len(audio),
                'resolution': f'{int(width)}x{int(height)}' if width and height else 'Unknown',
                'size_bytes': size_bytes, 'duration_sec': seconds,
                'size_mb': rounded(size_mib, 2), 'duration_min': rounded(minutes, 2),
                'efficiency_mb_per_hour': rounded(efficiency, 2),
            })
    return data, skipped
