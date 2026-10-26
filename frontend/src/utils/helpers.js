export const RESOLUTION_ORDER = [
  '8K', '5K', '4K / UHD', '2K / 1440p', 'Full HD / 1080p', 'HD / 720p',
  'SD / 576p', 'SD / 540p', 'SD / 480p', 'SD / 404p', 'SD / 384p', '360p', '240p', '144p', 'Unknown',
];

export function categorizeResolution(resolution) {
  const match = typeof resolution === 'string' && resolution.trim().match(/^(\d+)\s*x\s*(\d+)$/i);
  if (!match) return 'Unknown';
  const width = Math.max(Number(match[1]), Number(match[2]));
  const height = Math.min(Number(match[1]), Number(match[2]));
  if (!width || !height) return 'Unknown';
  // Enclosing dimension tiers keep cropped and portrait variants consistent.
  const tiers = [
    [256, 144, '144p'], [426, 240, '240p'], [640, 360, '360p'],
    [682, 384, 'SD / 384p'], [720, 404, 'SD / 404p'], [854, 480, 'SD / 480p'],
    [960, 544, 'SD / 540p'], [1024, 576, 'SD / 576p'], [1280, 962, 'HD / 720p'],
    [2048, 1088, 'Full HD / 1080p'], [2560, 1448, '2K / 1440p'],
    [4096, 3072, '4K / UHD'], [5120, 3072, '5K'], [8192, 6144, '8K'],
  ];
  return tiers.find(([w, h]) => width <= w && height <= h)?.[2] || 'Unknown';
}

export function applyFilters(data, filters) {
  const term = filters.search.trim().toLowerCase();
  return data.filter(item =>
    (!term || ['name', 'series_name', 'path'].some(key => String(item[key] ?? '').toLowerCase().includes(term))) &&
    (!filters.supportedFormats.length || filters.supportedFormats.includes(item.video_codec)) &&
    (!filters.resolutionGroups.length || filters.resolutionGroups.includes(categorizeResolution(item.resolution))) &&
    (!filters.types.length || filters.types.includes(item.type)),
  );
}

export function bitrateMbps(item) {
  const bytes = item.size_bytes ?? item.size_mb * 1024 ** 2;
  const seconds = item.duration_sec ?? item.duration_min * 60;
  return Number.isFinite(bytes) && bytes > 0 && Number.isFinite(seconds) && seconds > 0
    ? bytes * 8 / seconds / 1_000_000 : null;
}

export function buildBitrateHistogram(data, numBins = 100) {
  let maximum = 0;
  let included = 0;
  for (const item of data) {
    const bitrate = bitrateMbps(item);
    if (bitrate !== null) {
      maximum = Math.max(maximum, bitrate);
      included++;
    }
  }
  if (!maximum) return { bins: [], excluded: data.length };
  const width = maximum / numBins;
  const bins = Array.from({ length: numBins }, (_, i) => ({ start: i * width, end: (i + 1) * width, count: 0, size: 0, duration: 0 }));
  for (const item of data) {
    const bitrate = bitrateMbps(item);
    if (bitrate === null) continue;
    const bin = bins[Math.min(numBins - 1, Math.floor(bitrate / width))];
    bin.count++;
    bin.size += item.size_bytes != null ? item.size_bytes / 1024 ** 2 : item.size_mb;
    bin.duration += item.duration_sec != null ? item.duration_sec / 60 : item.duration_min;
  }
  return { bins, excluded: data.length - included };
}

export function aggregate(data, key, mode) {
  const totals = new Map();
  for (const row of data) {
    const label = key === 'resolution' ? categorizeResolution(row[key]) : String(row[key] ?? 'Unknown');
    const value = mode === 'size' ? row.size_mb : mode === 'duration' ? row.duration_min : 1;
    totals.set(label, (totals.get(label) || 0) + (Number.isFinite(value) ? value : 0));
  }
  return Array.from(totals);
}

export function csvCell(value) {
  if (value == null) return '';
  let string = String(value);
  if (typeof value === 'string' && /^(?:[=+\-@\t\r\n]|\s+[=+\-@])/.test(string)) string = "'" + string;
  return /[,"\r\n]/.test(string) ? `"${string.replace(/"/g, '""')}"` : string;
}

export function serializeCSV(rows, columns) {
  return [columns.map(col => csvCell(col.header)).join(','), ...rows.map(row => columns.map(col => csvCell(row[col.accessorKey])).join(','))].join('\r\n');
}
