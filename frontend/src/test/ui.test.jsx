import { useState } from 'react';
import { fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Filters from '../components/Filters';
import MediaTable from '../components/MediaTable';
import MediaAnalyzer from '../pages/MediaAnalyzer';
import useMediaData from '../hooks/useMediaData';

vi.mock('../components/Charts', () => ({ default: () => <div>Charts</div> }));
const media = [{ id: 'movie', name: 'Movie', type: 'Movie', path: '/media/Audit #1?.mkv', download_url: '/movies/Audit%20%231%3F.mkv', video_codec: 'HEVC', resolution: '1920x1080', size_mb: 1024, duration_min: 60, efficiency_mb_per_hour: 1024 }];
const reply = (body = media, headers = {}, status = 200) => ({ ok: status < 400, status, headers: new Headers(headers), json: async () => body });

describe('filters and table', () => {
  it('keeps search and codec selections together and resets them predictably', async () => {
    function Harness() {
      const [filters, setFilters] = useState({ search: '', supportedFormats: [], resolutionGroups: [], types: [], hiddenColumns: [] });
      return <><Filters data={media} filters={filters} setFilters={setFilters} /><output>{JSON.stringify(filters)}</output></>;
    }
    render(<Harness />);
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Movie' } });
    fireEvent.click(screen.getByLabelText('HEVC'));
    await new Promise(resolve => setTimeout(resolve, 350));
    expect(screen.getByRole('searchbox').value).toBe('Movie');
    expect(screen.getByLabelText('HEVC').checked).toBe(true);
    expect(screen.getByRole('status').textContent).toContain('"supportedFormats":["HEVC"]');
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(screen.getByRole('searchbox').value).toBe('');
    expect(screen.getByLabelText('HEVC').checked).toBe(false);
  });
  it('renders only supplied encoded download URLs and meaningful empty pagination', () => {
    const { rerender } = render(<MediaTable data={media} hiddenColumns={[]} />);
    expect(screen.getByRole('link').getAttribute('href')).toBe('/movies/Audit%20%231%3F.mkv');
    rerender(<MediaTable data={[]} hiddenColumns={[]} />);
    expect(screen.getByText('Page 0 of 0')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Export CSV' }).disabled).toBe(true);
  });
  it('supports keyboard-sortable headers and column visibility', () => {
    render(<MediaTable data={media} />);
    fireEvent.click(screen.getByRole('button', { name: 'Name' }));
    expect(screen.getByRole('button', { name: /Name/ }).closest('th').getAttribute('aria-sort')).toBe('ascending');
    fireEvent.click(screen.getByLabelText('Version'));
    expect(screen.queryByRole('button', { name: 'Version' })).toBeNull();
  });
});

describe('request lifecycle and refresh', () => {
  it('retains the table and filters when refreshing fails, and permits retry', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(reply(media, { 'X-Scanned-At': '2026-10-26T12:00:00Z' }))
      .mockResolvedValueOnce(reply({ error: 'Jellyfin timed out. Please try again.' }, {}, 502))
      .mockResolvedValue(reply());
    vi.stubGlobal('fetch', fetchMock);
    render(<MediaAnalyzer />);
    await screen.findByRole('link');
    fireEvent.click(screen.getByLabelText('HEVC'));
    fireEvent.click(screen.getByRole('button', { name: 'Reload Data' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('link').textContent).toContain('Audit');
    expect(screen.getByLabelText('HEVC').checked).toBe(true);
    expect(screen.getByRole('button', { name: 'Reload Data' }).disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Reload Data' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });
  it('shows safe stale snapshot warnings', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(media, { 'X-Cache-Stale': 'true', 'X-Refresh-Error': 'Jellyfin timed out.', 'X-Skipped-Records': '2' })));
    render(<MediaAnalyzer />);
    expect((await screen.findByRole('alert')).textContent).toBe('Jellyfin timed out.');
    expect(screen.getByText(/2 records/)).toBeTruthy();
  });
  it('ignores an older response after a new request has completed', async () => {
    let finishFirst;
    vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(new Promise(resolve => { finishFirst = resolve; })).mockResolvedValueOnce(reply([{ ...media[0], name: 'New' }])));
    function Harness() {
      const { data, reload } = useMediaData();
      return <><button onClick={reload}>Reload</button><output>{data[0]?.name}</output></>;
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    await screen.findByText('New');
    await act(async () => { finishFirst(reply(media)); });
    expect(screen.getByText('New')).toBeTruthy();
    expect(screen.queryByText('Movie')).toBeNull();
  });
  it('aborts the pending request on unmount', () => {
    let signal;
    vi.stubGlobal('fetch', vi.fn((_, options) => { signal = options.signal; return new Promise(() => {}); }));
    function Harness() { useMediaData(); return null; }
    const { unmount } = render(<Harness />);
    unmount();
    expect(signal.aborted).toBe(true);
  });
});
