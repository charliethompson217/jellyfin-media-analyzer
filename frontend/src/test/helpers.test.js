import { describe, expect, it } from 'vitest';
import { aggregate, applyFilters, bitrateMbps, buildBitrateHistogram, categorizeResolution, csvCell, serializeCSV } from '../utils/helpers';

const filters = { search: '', supportedFormats: [], resolutionGroups: [], types: [] };
describe('media calculations', () => {
  it.each([
    ['2560x1440', '2K / 1440p'], ['2560x1438', '2K / 1440p'], ['5120x2880', '5K'], ['5120x2160', '5K'],
    ['1920x800', 'Full HD / 1080p'], ['1080x1920', 'Full HD / 1080p'], ['720x576', 'SD / 576p'],
    ['3840x1600', '4K / UHD'], [null, 'Unknown'], ['garbage', 'Unknown'], ['0x1080', 'Unknown'],
  ])('classifies %s consistently', (input, expected) => expect(categorizeResolution(input)).toBe(expected));

  it('converts binary bytes to decimal Mbps without early rounding', () => {
    expect(bitrateMbps({ size_bytes: 1024 ** 3, duration_sec: 3600 })).toBeCloseTo(2.386092942222222);
    expect(bitrateMbps({ size_mb: 1024, duration_min: 60 })).toBeCloseTo(2.386092942222222);
    expect(bitrateMbps({ size_bytes: null, size_mb: null, duration_min: 60 })).toBeNull();
  });
  it('handles large libraries and conserves the histogram totals', () => {
    const row = { size_bytes: 1024 ** 3, duration_sec: 3600 };
    const { bins, excluded } = buildBitrateHistogram([...Array(200000).fill(row), {}]);
    expect(bins.reduce((sum, bin) => sum + bin.count, 0)).toBe(200000);
    expect(bins.reduce((sum, bin) => sum + bin.size, 0)).toBe(200000 * 1024);
    expect(bins.reduce((sum, bin) => sum + bin.duration, 0)).toBe(200000 * 60);
    expect(bins.at(-1).end).toBeCloseTo(bitrateMbps(row));
    expect(excluded).toBe(1);
    expect(buildBitrateHistogram([]).bins).toEqual([]);
  });
  it('combines advertised search fields with codec and type filters', () => {
    const rows = [{ name: 'Movie', series_name: '', path: '/movie.mkv', video_codec: 'HEVC', type: 'Movie', size_mb: 123 }];
    expect(applyFilters(rows, { ...filters, search: 'movie', supportedFormats: ['HEVC'], types: ['Movie'] })).toHaveLength(1);
    expect(applyFilters(rows, { ...filters, search: '123' })).toHaveLength(0);
    expect(aggregate([{ hdr_info: null, size_mb: null }], 'hdr_info', 'size')).toEqual([['Unknown', 0]]);
  });
});

describe('spreadsheet-safe CSV', () => {
  it.each(['=1+1', '+SUM(A1)', '-cmd', '@SUM(A1)', '  =1+1', '\t=1+1', '\r=1+1'])('neutralizes formula-like strings %s', value => {
    expect(csvCell(value).replace(/^"/, '')).toMatch(/^'/);
  });
  it('preserves real numeric cells and escapes every CSV line separator', () => {
    expect(csvCell(-12)).toBe('-12');
    expect(csvCell('a,"b"\rline')).toBe('"a,""b""\rline"');
    expect(serializeCSV([{ name: '=1+1' }, { name: '普通话' }], [{ accessorKey: 'name', header: 'Name' }])).toBe("Name\r\n'=1+1\r\n普通话");
  });
});
