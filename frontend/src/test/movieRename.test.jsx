import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MovieRenameDialog from '../components/MovieRenameDialog';

const row = { id: 'movie-version', title: 'Pulp Fiction', expected_component: 'Pulp Fiction (1994)' };
const oldStem = 'Pulp Fiction (1995) - [Bluray-1080p-1301kbps-H.264]';
const newStem = 'Pulp Fiction (1994) - [Bluray-1080p-1301kbps-H.264]';
const preview = {
  token: 'signed-preview', prefix: 'Pulp Fiction (1994)', suggested_prefix: 'Pulp Fiction (1994)',
  source_directory: '/srv/jellyfin/media/movies/Pulp Fiction (1995)',
  destination_directory: '/srv/jellyfin/media/movies/Pulp Fiction (1994)',
  video_count: 4, changed_filenames: 16, can_apply: true,
  files: [
    { from: oldStem + '.mp4', to: newStem + '.mp4', renamed: true, reason: 'Movie version' },
    { from: oldStem + '.eng.srt', to: newStem + '.eng.srt', renamed: true, reason: 'Associated file' },
    { from: oldStem + '.nfo', to: newStem + '.nfo', renamed: true, reason: 'Associated file' },
    { from: 'movie.nfo', to: 'movie.nfo', renamed: false, reason: 'Shared metadata / artwork' },
    { from: 'folder.jpg', to: 'folder.jpg', renamed: false, reason: 'Shared metadata / artwork' },
  ],
};
const reply = (body, status = 200) => ({ ok: status < 400, json: async () => body });

afterEach(() => vi.unstubAllGlobals());

describe('movie rename dialog', () => {
  it('previews the entire folder and applies only the signed plan', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(reply(preview))
      .mockResolvedValueOnce(reply({ ...preview, token: 'custom-plan', prefix: 'My Exact Name (1994)' }))
      .mockResolvedValueOnce(reply({ video_count: 4 }));
    vi.stubGlobal('fetch', fetchMock);
    const renamed = vi.fn();
    render(<MovieRenameDialog row={row} snapshotRevision="snapshot-1" onClose={vi.fn()} onRenamed={renamed} />);
    const dialog = await screen.findByRole('dialog', { name: 'Rename movie folder and files' });
    await waitFor(() => expect(within(dialog).getByText(oldStem + '.eng.srt')).toBeTruthy());
    expect(within(dialog).getByText(newStem + '.nfo')).toBeTruthy();
    expect(within(dialog).getAllByText('movie.nfo')).toHaveLength(2);
    expect(within(dialog).getByText('/srv/jellyfin/media/movies/Pulp Fiction (1995)')).toBeTruthy();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ row_id: row.id, snapshot_revision: 'snapshot-1' });
    const prefix = within(dialog).getByLabelText('Shared folder and filename prefix');
    fireEvent.change(prefix, { target: { value: 'My Exact Name (1994)' } });
    expect(within(dialog).getByRole('button', { name: 'Apply folder rename' }).disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Preview changes' }));
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Apply folder rename' }).disabled).toBe(false));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ prefix: 'My Exact Name (1994)', snapshot_revision: 'snapshot-1' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply folder rename' }));
    await waitFor(() => expect(renamed).toHaveBeenCalledWith({ video_count: 4 }));
    expect(fetchMock.mock.calls[2][0]).toBe('/api/movie-renames/apply');
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ token: 'custom-plan' });
    for (const [, options] of fetchMock.mock.calls) expect(options.headers['X-Media-Analyzer-Action']).toBe('rename');
    expect(fetchMock.mock.calls.every(([url]) => !url.includes('.nfo'))).toBe(true);
  });

  it('requests the checker suggestion and displays a safe server error without applying', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(reply(preview))
      .mockResolvedValueOnce(reply({ error: 'A different directory already uses that name.' }, 409))
      .mockResolvedValueOnce(reply(preview));
    vi.stubGlobal('fetch', fetchMock);
    render(<MovieRenameDialog row={row} snapshotRevision="snapshot-1" onClose={vi.fn()} onRenamed={vi.fn()} />);
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getByText('Suggested prefix: Pulp Fiction (1994)')).toBeTruthy());
    fireEvent.change(within(dialog).getByLabelText('Shared folder and filename prefix'), { target: { value: 'Existing' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Preview changes' }));
    expect((await within(dialog).findByRole('alert')).textContent).toContain('already uses that name');
    expect(within(dialog).getByRole('button', { name: 'Apply folder rename' }).disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Use checker suggestion' }));
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Apply folder rename' }).disabled).toBe(false));
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ row_id: row.id, snapshot_revision: 'snapshot-1' });
  });
});
