import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { serializeCSV } from '../utils/helpers';
import { categoryLabel, filterPathResults, PATH_CATEGORIES, PATH_EXPORT_COLUMNS, pathExportRows } from '../utils/moviePaths';
import MovieRenameDialog from './MovieRenameDialog';

const PAGE_SIZE = 25;
const CONTROL = 'border border-gray-300 rounded-md px-3 py-2 text-sm bg-white';

function ComponentDetails({ row, side }) {
  const label = side === 'folder' ? 'Folder' : 'Filename';
  return <section className="min-w-0">
    <h4 className="font-semibold mb-2">{label}</h4>
    <dl className="space-y-2 text-sm">
      <div><dt className="text-gray-500">Original component</dt><dd className="break-words">{row[`${side}_component`]}</dd></div>
      <div><dt className="text-gray-500">Used for matching</dt><dd className="break-words">{row[`${side}_cleaned_component`]}</dd></div>
      <div><dt className="text-gray-500">Result</dt><dd>{categoryLabel(row[`${side}_category`])}</dd></div>
      <div><dt className="text-gray-500">Title similarity</dt><dd>{row[`${side}_title_similarity`]}%</dd></div>
      <div><dt className="text-gray-500">Year difference</dt><dd>{row[`${side}_year_delta`] ?? 'Unknown'}</dd></div>
      <div><dt className="text-gray-500">Matching variants</dt><dd>{row[`${side}_best_variant_pair`]?.join(' → ')}</dd></div>
      {row[`${side}_removed_version_tags`]?.length > 0 && <div><dt className="text-gray-500">Misplaced version tags</dt><dd>{row[`${side}_removed_version_tags`].join(', ')}</dd></div>}
    </dl>
  </section>;
}

export default function MoviePathCheck({ snapshot, mediaLoading, onLibraryChanged }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [threshold, setThreshold] = useState('92');
  const [filters, setFilters] = useState({ search: '', category: '', flag: '', issuesOnly: true });
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState(new Set());
  const [renameRow, setRenameRow] = useState(null);
  const [notice, setNotice] = useState(null);
  const active = useRef(null);
  const timer = useRef(null);
  useEffect(() => () => { active.current?.abort(); active.current = null; clearTimeout(timer.current); }, []);

  const validThreshold = threshold.trim() !== '' && Number.isFinite(Number(threshold)) && Number(threshold) >= 0 && Number(threshold) <= 100;
  const runCheck = async () => {
    if (!validThreshold) return;
    active.current?.abort();
    clearTimeout(timer.current);
    const controller = new AbortController();
    active.current = controller;
    timer.current = setTimeout(() => controller.abort('timeout'), 300000);
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/movie-paths?spelling_threshold=${encodeURIComponent(threshold)}`, { signal: controller.signal });
      const body = await response.json();
      if (active.current !== controller || controller.signal.aborted) return;
      if (!response.ok) throw new Error(body.error || 'Unable to check movie paths. Please try again.');
      if (!Array.isArray(body.rows) || !body.summary || !Array.isArray(body.summary.categories)) throw new Error('The server returned an invalid path report.');
      setReport(body);
      setPage(0);
      setExpanded(new Set());
    } catch (failure) {
      if (active.current !== controller) return;
      if (!controller.signal.aborted || controller.signal.reason === 'timeout') {
        setError(controller.signal.reason === 'timeout' ? 'The path check timed out. Please retry.' : failure.message);
      }
    } finally {
      if (active.current === controller) { clearTimeout(timer.current); setLoading(false); }
    }
  };
  const filtered = useMemo(() => filterPathResults(report?.rows || [], filters), [report, filters]);
  const pageCount = Math.ceil(filtered.length / PAGE_SIZE);
  const currentPage = Math.min(page, Math.max(0, pageCount - 1));
  const visible = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const updateFilter = (key, value) => { setFilters(current => ({ ...current, [key]: value })); setPage(0); };
  const exportCSV = () => {
    const csv = serializeCSV(pathExportRows(filtered), PATH_EXPORT_COLUMNS);
    const url = URL.createObjectURL(new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8;' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `movie-path-check-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const reportRevision = report?.snapshot_revision || report?.scanned_at;
  const outdated = report && snapshot?.scannedAt && reportRevision !== (snapshot.revision || snapshot.scannedAt);
  const renamed = async result => {
    setRenameRow(null);
    setNotice(`Renamed ${result.video_count} movie versions and their associated files. ${result.warning || 'Run a library scan in Jellyfin to update its own paths.'}`);
    await runCheck();
    await onLibraryChanged?.();
  };

  return <div className="space-y-6">
    <section className="bg-white rounded-lg border border-gray-200 shadow-sm p-6">
      <div className="flex flex-wrap items-center gap-3 mb-2"><h2 className="text-2xl font-bold">Movie Path Check</h2>{report && <span className="rounded-full bg-blue-50 px-3 py-1 text-xs text-blue-800">{report.rename_enabled ? 'Folder renaming enabled' : 'Read-only'}</span>}</div>
      <p className="text-gray-600">Compare movie folder and file names against Jellyfin titles and years. All movie versions in the library snapshot are included; overview filters do not apply.</p>
      <div className="flex flex-wrap items-end gap-4 mt-5">
        <label className="text-sm font-medium">Spelling similarity threshold (%)
          <input type="number" min="0" max="100" step="0.1" value={threshold} onChange={e => setThreshold(e.target.value)} className={`${CONTROL} block mt-1 w-32`} />
        </label>
        <button type="button" onClick={runCheck} disabled={loading || mediaLoading || !validThreshold || !snapshot} className="px-5 py-2 rounded-md bg-blue-600 text-white font-medium disabled:opacity-50">{loading ? 'Checking paths…' : 'Run Path Check'}</button>
      </div>
      {!validThreshold && <p className="text-sm text-red-700 mt-2">Enter a threshold from 0 to 100.</p>}
      {!snapshot && <p className="text-sm text-gray-600 mt-3">Load the media library before running a check.</p>}
      <p className="text-xs text-gray-500 mt-4">Checks use the paths reported by Jellyfin and compare names, not file existence. The overall category uses the better-matching folder or filename, with differences flagged separately.</p>
    </section>
    {error && <div role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-4 text-amber-900">{error}{report && ' Showing the last completed report.'}</div>}
    {notice && <p role="status" className="p-4 rounded-md border border-green-200 bg-green-50 text-green-900">{notice}</p>}
    {outdated && <p role="status" className="text-sm text-amber-800">The library snapshot has changed. Run Path Check again to update these results.</p>}
    {report && <>
      {!report.rename_enabled && <p className="text-sm text-gray-600">To rename movie folders and associated files here, set ENABLE_RENAMING=true on the server and grant its service account access to the movie directories.</p>}
      <p className="text-sm text-gray-600" role="status">{report.summary.checked} movie files checked against the snapshot from {new Date(report.scanned_at).toLocaleString()} · Spelling threshold: {report.spelling_threshold}%</p>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">{[
        ['Movie files / versions', report.summary.total_movies], ['Naming issues', report.summary.needs_review],
        ['Folder/file differences', report.summary.folder_file_mismatches], ['Version tag issues', report.summary.bad_version_tags], ['Not checked', report.summary.uncheckable],
      ].map(([label, count]) => <div key={label} className="bg-white rounded-lg border border-gray-200 p-4"><div className="text-sm text-gray-600">{label}</div><div className="text-2xl font-bold">{count}</div></div>)}</div>
      <section className="bg-white rounded-lg border border-gray-200 shadow-sm p-5">
        <div className="flex flex-wrap gap-4 items-end">
          <label className="text-sm font-medium flex-1 min-w-48">Search movie paths<input type="search" value={filters.search} onChange={e => updateFilter('search', e.target.value)} placeholder="Title, year, path, or notes" className={`${CONTROL} block mt-1 w-full`} /></label>
          <label className="text-sm font-medium">Category<select value={filters.category} onChange={e => updateFilter('category', e.target.value)} className={`${CONTROL} block mt-1`}><option value="">All categories</option>{PATH_CATEGORIES.map(([key, label]) => <option key={key} value={key}>{label} ({report.summary.categories.find(item => item.category === key)?.count || 0})</option>)}</select></label>
          <label className="text-sm font-medium">Flags<select value={filters.flag} onChange={e => updateFilter('flag', e.target.value)} className={`${CONTROL} block mt-1`}><option value="">All flags</option><option value="folder">Folder/file differences</option><option value="version">Version tag issues</option><option value="uncheckable">Not checked</option></select></label>
          <label className="text-sm flex items-center gap-2 py-2"><input type="checkbox" checked={filters.issuesOnly} onChange={e => updateFilter('issuesOnly', e.target.checked)} />Only show issues</label>
          <button type="button" onClick={exportCSV} disabled={!filtered.length} className="rounded-md bg-blue-600 text-white px-4 py-2 disabled:opacity-50">Export Path CSV</button>
        </div>
        <p className="text-sm text-gray-500 mt-4">{filtered.length} of {report.rows.length} movie files shown. CSV export includes all filtered results.</p>
      </section>
      <section aria-label="Movie path results" className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="overflow-x-auto" role="region" tabIndex={0} aria-label="Scrollable path results">
          <table className="w-full text-sm text-left"><caption className="sr-only">Movie folder and filename comparison results</caption>
            <thead className="bg-gray-50"><tr>{['Movie / version', 'Expected title and year', 'Overall result', 'Folder / filename', 'Details'].map(label => <th key={label} scope="col" className="px-4 py-3 whitespace-nowrap">{label}</th>)}</tr></thead>
            <tbody>{visible.map(row => <Fragment key={row.id}>
              <tr className="border-t border-gray-200 align-top">
                <th scope="row" className="px-4 py-4 font-normal min-w-48"><div className="font-semibold">{row.title}{row.year ? ` (${row.year})` : ''}</div>{row.version_name && <div className="text-gray-500">{row.version_name}</div>}</th>
                <td className="px-4 py-4 min-w-48">{row.expected_component || 'Unavailable'}</td>
                <td className="px-4 py-4 min-w-48"><span className={`inline-block rounded-full px-3 py-1 text-xs font-medium ${row.needs_review ? 'bg-amber-50 text-amber-900' : 'bg-green-50 text-green-800'}`}>{categoryLabel(row.category)}</span><div className="mt-2 text-gray-600">{row.status === 'checked' ? `Best title similarity: ${row.best_title_similarity}%` : row.uncheckable_reason}</div></td>
                <td className="px-4 py-4 min-w-48">{row.status === 'checked' ? <><div>{row.folder_file_exact_match ? 'Same title/year component' : 'Folder/file differ'}</div>{row.incorrectly_formatted_version_tag && <div className="text-amber-800 mt-1">Misplaced version tag</div>}</> : 'Not checked'}</td>
                <td className="px-4 py-4"><button type="button" aria-expanded={expanded.has(row.id)} aria-controls={`path-details-${row.id}`} aria-label={`Details for ${row.title} ${row.version_name}`} className="text-blue-700 underline" onClick={() => setExpanded(current => { const next = new Set(current); if (next.has(row.id)) next.delete(row.id); else next.add(row.id); return next; })}>{expanded.has(row.id) ? 'Hide details' : 'View details'}</button>
                  {report.rename_enabled && <button type="button" disabled={outdated || loading || mediaLoading || !row.path} onClick={() => setRenameRow(row)} aria-label={`Rename folder for ${row.title} ${row.version_name}`} className="block mt-3 text-blue-700 underline disabled:opacity-50">Rename folder &amp; files</button>}
                </td>
              </tr>
              {expanded.has(row.id) && <tr id={`path-details-${row.id}`} className="border-t border-gray-100 bg-gray-50"><td colSpan={5} className="p-5">
                <p className="text-xs text-gray-500 mb-1">Jellyfin path</p><p className="break-all font-mono text-sm mb-4">{row.path || 'Unknown'}</p>
                {row.notes && <p className="text-sm mb-4">{row.notes}</p>}
                {row.status === 'checked' && <><p className="text-sm mb-4">Best match source: {row.bucket_source}. Folder: {categoryLabel(row.folder_category)}. Filename: {categoryLabel(row.file_category)}.</p><div className="grid grid-cols-1 md:grid-cols-2 gap-6"><ComponentDetails row={row} side="folder" /><ComponentDetails row={row} side="file" /></div></>}
              </td></tr>}
            </Fragment>)}</tbody>
          </table>
          {!visible.length && <p className="p-8 text-center text-gray-600">{report.rows.length ? 'No movie paths match these filters. Adjust filters or clear “Only show issues” to include exact matches.' : 'No movie files are available in this snapshot.'}</p>}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 bg-gray-50 border-t border-gray-200 p-4 text-sm"><span>Page {pageCount ? currentPage + 1 : 0} of {pageCount}</span><div className="flex gap-2"><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)} className="border px-3 py-2 rounded-md disabled:opacity-50">Previous results</button><button type="button" disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)} className="border px-3 py-2 rounded-md disabled:opacity-50">Next results</button></div></div>
      </section>
    </>}
    {renameRow && <MovieRenameDialog key={renameRow.id} row={renameRow} snapshotRevision={reportRevision} onClose={() => setRenameRow(null)} onRenamed={renamed} />}
  </div>;
}
