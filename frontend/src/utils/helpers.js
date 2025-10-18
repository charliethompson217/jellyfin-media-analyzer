import _ from 'lodash';

export function categorizeResolution(resolution) {
  if (!resolution) return 'Unknown';

  const cleanRes = resolution.trim().toLowerCase();
  const parts = cleanRes.split('x');
  if (parts.length !== 2) return 'Unknown';

  let w = parseInt(parts[0], 10);
  let h = parseInt(parts[1], 10);
  if (isNaN(w) || isNaN(h) || w <= 0 || h <= 0) return 'Unknown';

  // Orientation-agnostic: assume max as width, min as height
  const width = Math.max(w, h);
  const height = Math.min(w, h);

  // Lookup for exacts/variants (overrides fuzzy)
  const lookup = {
    '7680x4320': '8K',
    '5120x2880': '5K',
    '3840x2160': '4K / UHD',
    '4096x2160': '4K / UHD',
    '2560x1440': '2K / 1440p',
    '2048x1080': '2K / 1440p',
    '1920x1080': 'Full HD / 1080p',
    '1920x1088': 'Full HD / 1080p',
    '1920x1072': 'Full HD / 1080p',
    '1920x1078': 'Full HD / 1080p',
    '1280x720': 'HD / 720p',
    '854x480': 'SD / 480p',
    '720x480': 'SD / 480p',
    '640x360': '360p'
  };

  const key = `${width}x${height}`;
  if (lookup[key]) return lookup[key];

  // Jellyfin-inspired fuzzy switch on width with height caps
  // https://github.com/jellyfin/jellyfin/blob/ac5efb47754e9fa1d670ae4e9ed6c44c5ccb3c73/MediaBrowser.Model/Entities/MediaStream.cs#L714
  if (width <= 256 && height <= 144) return '144p';
  if (width <= 426 && height <= 240) return '240p';
  if (width <= 640 && height <= 360) return '360p';
  if (width <= 682 && height <= 384) return 'SD / 384p';
  if (width <= 720 && height <= 404) return 'SD / 404p';
  if (width <= 854 && height <= 480) return 'SD / 480p';
  if (width <= 960 && height <= 544) return 'SD / 540p';
  if (width <= 1024 && height <= 576) return 'SD / 576p';
  if (width <= 1280 && height <= 962) return 'HD / 720p';
  if (width <= 2560 && height <= 1440) return 'Full HD / 1080p';
  if (width <= 4096 && height <= 3072) return '4K / UHD';
  if (width <= 8192 && height <= 6144) return '8K';

  return 'Unknown';
}

export function applyFilters(data, filters) {
  let filtered = data;
  if (filters.search) {
    const term = filters.search.toLowerCase();
    filtered = filtered.filter(item => Object.values(item).some(val => String(val).toLowerCase().includes(term)));
  }
  if (filters.supportedFormats.length) {
    filtered = filtered.filter(item => filters.supportedFormats.includes(item.video_codec));
  }
  if (filters.resolutionGroups.length) {
    filtered = filtered.filter(item => filters.resolutionGroups.includes(categorizeResolution(item.resolution)));
  }
  if (filters.types.length) {
    filtered = filtered.filter(item => filters.types.includes(item.type));
  }
  return filtered;
}