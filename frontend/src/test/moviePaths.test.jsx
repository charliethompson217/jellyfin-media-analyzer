import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import MoviePathCheck from '../components/MoviePathCheck';
import MediaAnalyzer from '../pages/MediaAnalyzer';
import { filterPathResults, PATH_CATEGORIES } from '../utils/moviePaths';

vi.mock('../components/Charts', () => ({ default: () => <div>Charts</div> }));
const scannedAt = '2026-10-26T12:00:00Z';
const snapshot = { scannedAt };
const exact = {
  id: 'matrix', title: 'The Matrix', year: '1999', version_name: 'Standard',
  path: '/home/jellyfin/media/movies/The Matrix (1999)/The Matrix (1999).mkv',
  expected_component: 'The Matrix (1999)', category: PATH_CATEGORIES[0][0], status: 'checked', needs_review: false,
  folder_file_exact_match: true, incorrectly_formatted_version_tag: false, best_title_similarity: 100,
  folder_component: 'The Matrix (1999)', file_component: 'The Matrix (1999)', bucket_source: 'both',
  folder_category: PATH_CATEGORIES[0][0], file_category: PATH_CATEGORIES[0][0],
  folder_cleaned_component: 'The Matrix (1999)', file_cleaned_component: 'The Matrix (1999)',
  folder_title_similarity: 100, file_title_similarity: 100, folder_year_delta: 0, file_year_delta: 0,
  folder_removed_version_tags: [], file_removed_version_tags: [], folder_best_variant_pair: ['raw', 'raw'], file_best_variant_pair: ['raw', 'raw'], notes: '',
};
const issue = { ...exact, id: 'extended', version_name: 'Extended', needs_review: true, folder_file_exact_match: false,
  incorrectly_formatted_version_tag: true, file_removed_version_tags: ['Extended'], file_component: 'The Matrix Extended (1999)', notes: 'incorrect version tag in file' };
const wrong = { ...exact, id: 'alien', title: 'Alien', expected_component: 'Alien (1979)', year: '1979', category: PATH_CATEGORIES[6][0], needs_review: true, best_title_similarity: 25 };
const missing = { id: 'unknown', title: 'Unknown Year', year: '', path: '/movies/Unknown.mkv', status: 'uncheckable', needs_review: true, uncheckable_reason: 'Missing Jellyfin production year.' };
function report(rows = [exact, issue, wrong, missing]) {
  return { rows, scanned_at: scannedAt, spelling_threshold: 92, summary: {
    checked: rows.filter(row => row.status === 'checked').length, total_movies: rows.length,
    needs_review: rows.filter(row => row.status === 'checked' && row.needs_review).length,
    uncheckable: rows.filter(row => row.status === 'uncheckable').length,
    folder_file_mismatches: rows.filter(row => row.status === 'checked' && !row.folder_file_exact_match).length,
    bad_version_tags: rows.filter(row => row.incorrectly_formatted_version_tag).length,
    categories: PATH_CATEGORIES.map(([category]) => ({ category, count: rows.filter(row => row.category === category).length })),
  } };
}
const reply = (body, status = 200) => ({ ok: status < 400, json: async () => body });
const results = () => screen.getByRole('region', { name: 'Movie path results' });
async function run(rows) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(report(rows))));
  render(<MoviePathCheck snapshot={snapshot} mediaLoading={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'Run Path Check' }));
  await screen.findByRole('region', { name: 'Movie path results' });
}

describe('movie path workflow', () => {
  it('runs against the library snapshot with the selected threshold and defaults to issues', async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(report()));
    vi.stubGlobal('fetch', fetchMock);
    render(<MoviePathCheck snapshot={snapshot} mediaLoading={false} />);
    fireEvent.change(screen.getByLabelText('Spelling similarity threshold (%)'), { target: { value: '95' } });
    fireEvent.click(screen.getByRole('button', { name: 'Run Path Check' }));
    await screen.findByRole('region', { name: 'Movie path results' });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/movie-paths?spelling_threshold=95');
    expect(within(results()).getByText('Extended')).toBeTruthy();
    expect(screen.getByText('3 of 4 movie files shown. CSV export includes all filtered results.')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Only show issues'));
    expect(screen.getByText('4 of 4 movie files shown. CSV export includes all filtered results.')).toBeTruthy();
  });

  it('shows folder and file explanations separately, including the original container path', async () => {
    await run([issue]);
    fireEvent.click(screen.getByRole('button', { name: 'Details for The Matrix Extended' }));
    expect(within(results()).getByText(issue.path)).toBeTruthy();
    expect(within(results()).getByText('The Matrix Extended (1999)')).toBeTruthy();
    expect(within(results()).getByText('incorrect version tag in file')).toBeTruthy();
    expect(within(results()).getByText('Misplaced version tags')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Details for The Matrix Extended' }).getAttribute('aria-expanded')).toBe('true');
  });

  it('combines category, flag, and search filters and can show uncheckable rows', async () => {
    await run();
    fireEvent.change(screen.getByLabelText('Category'), { target: { value: PATH_CATEGORIES[6][0] } });
    expect(within(results()).getAllByText('Alien (1979)')).toHaveLength(2);
    expect(within(results()).queryByText('Extended')).toBeNull();
    fireEvent.change(screen.getByLabelText('Category'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Flags'), { target: { value: 'version' } });
    expect(within(results()).getByText('Extended')).toBeTruthy();
    expect(within(results()).queryAllByText('Alien (1979)')).toHaveLength(0);
    fireEvent.change(screen.getByLabelText('Search movie paths'), { target: { value: 'nothing matches' } });
    expect(within(results()).getByText(/No movie paths match/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Search movie paths'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Flags'), { target: { value: 'uncheckable' } });
    expect(within(results()).getByText('Missing Jellyfin production year.')).toBeTruthy();
  });

  it('retains a completed report after an unsuccessful recheck', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(reply(report([issue]))).mockResolvedValueOnce(reply({ error: 'Reload the media library before running a movie path check.' }, 409));
    vi.stubGlobal('fetch', fetchMock);
    render(<MoviePathCheck snapshot={snapshot} mediaLoading={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'Run Path Check' }));
    await screen.findByRole('region', { name: 'Movie path results' });
    fireEvent.click(screen.getByRole('button', { name: 'Run Path Check' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Showing the last completed report.');
    expect(within(results()).getByText('Extended')).toBeTruthy();
  });

  it('handles empty libraries and flags results from older snapshots', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(report([]))));
    const { rerender } = render(<MoviePathCheck snapshot={snapshot} mediaLoading={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'Run Path Check' }));
    await screen.findByRole('region', { name: 'Movie path results' });
    expect(within(results()).getByText('No movie files are available in this snapshot.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Export Path CSV' }).disabled).toBe(true);
    rerender(<MoviePathCheck snapshot={{ scannedAt: '2026-10-26T13:00:00Z' }} mediaLoading={false} />);
    expect(screen.getByText(/library snapshot has changed/)).toBeTruthy();
  });

  it('requires a loaded snapshot and a valid threshold', () => {
    const { rerender } = render(<MoviePathCheck snapshot={null} mediaLoading={false} />);
    expect(screen.getByRole('button', { name: 'Run Path Check' }).disabled).toBe(true);
    rerender(<MoviePathCheck snapshot={snapshot} mediaLoading={false} />);
    for (const value of ['101', '-1', '']) {
      fireEvent.change(screen.getByLabelText('Spelling similarity threshold (%)'), { target: { value } });
      expect(screen.getByRole('button', { name: 'Run Path Check' }).disabled).toBe(true);
    }
  });

  it('exports every filtered row across pages, with spreadsheet-safe strings', async () => {
    const rows = Array.from({ length: 30 }, (_, i) => ({ ...issue, id: String(i), title: i === 29 ? '=1+1' : `Movie ${i}` }));
    await run(rows);
    fireEvent.click(screen.getByRole('button', { name: 'Next results' }));
    expect(within(results()).getByText('Page 2 of 2')).toBeTruthy();
    const create = vi.fn().mockReturnValue('blob:report');
    const revoke = vi.fn();
    vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke });
    vi.stubGlobal('Blob', class { constructor(parts) { this.parts = parts; } });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole('button', { name: 'Export Path CSV' }));
      const csv = create.mock.calls[0][0].parts.join('');
      expect(csv).toContain('Movie 0');
      expect(csv).toContain('Movie 28');
      expect(csv).toContain("'=1+1");
      expect(csv).toContain('Extended');
      expect(csv).toContain('raw | raw');
      await act(async () => { vi.runOnlyPendingTimers(); });
      expect(revoke).toHaveBeenCalledWith('blob:report');
    } finally { vi.useRealTimers(); }
  });

  it('cancels the request when the component is unmounted', () => {
    let signal;
    vi.stubGlobal('fetch', vi.fn((_, options) => { signal = options.signal; return new Promise(() => {}); }));
    const { unmount } = render(<MoviePathCheck snapshot={snapshot} mediaLoading={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'Run Path Check' }));
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it('keeps the overview filters and path report when switching tools', async () => {
    const fetchMock = vi.fn(url => url.startsWith('/api/movie-paths') ? Promise.resolve(reply(report([issue]))) : Promise.resolve({ ...reply([
      { id: 'movie', name: 'The Matrix', type: 'Movie', video_codec: 'HEVC', resolution: '1920x1080', size_mb: 1000, duration_min: 120 },
    ]), headers: new Headers({ 'X-Scanned-At': scannedAt }) }));
    vi.stubGlobal('fetch', fetchMock);
    render(<MediaAnalyzer />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Reload Data' }).disabled).toBe(false));
    fireEvent.click(screen.getByLabelText('HEVC'));
    fireEvent.click(screen.getByRole('tab', { name: 'Movie Path Check' }));
    fireEvent.click(screen.getByRole('button', { name: 'Run Path Check' }));
    await screen.findByRole('region', { name: 'Movie path results' });
    fireEvent.click(screen.getByRole('tab', { name: 'Library Overview' }));
    expect(screen.getByLabelText('HEVC').checked).toBe(true);
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Library Overview' }), { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: 'Movie Path Check' }).getAttribute('aria-selected')).toBe('true');
    expect(within(results()).getByText('Extended')).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url]) => url.startsWith('/api/movie-paths'))).toHaveLength(1);
  });
});

describe('path result filtering', () => {
  it('does not hide problems when the overall category is an exact match', () => {
    expect(filterPathResults([exact, issue, missing], { issuesOnly: true })).toEqual([issue, missing]);
    expect(filterPathResults([exact, issue], { issuesOnly: true, category: exact.category, flag: 'folder' })).toEqual([issue]);
  });
});
