import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const HEADERS = { 'Content-Type': 'application/json', 'X-Media-Analyzer-Action': 'rename' };

export default function MovieRenameDialog({ row, snapshotRevision, onClose, onRenamed }) {
  const [prefix, setPrefix] = useState(row.expected_component || row.title || '');
  const [preview, setPreview] = useState(null);
  const [suggestion, setSuggestion] = useState(null);
  const [busy, setBusy] = useState('preview');
  const [error, setError] = useState(null);
  const active = useRef(null);
  const dialog = useRef(null);
  const requestPreview = useCallback(async (desiredPrefix) => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setBusy('preview');
    setError(null);
    setPreview(null);
    try {
      const response = await fetch('/api/movie-renames/preview', { method: 'POST', headers: HEADERS, signal: controller.signal,
        body: JSON.stringify({ row_id: row.id, snapshot_revision: snapshotRevision, ...(desiredPrefix === undefined ? {} : { prefix: desiredPrefix }) }) });
      const body = await response.json();
      if (active.current !== controller || controller.signal.aborted) return;
      if (!response.ok) throw new Error(body.error || 'Unable to preview this rename.');
      if (!body.token || !Array.isArray(body.files)) throw new Error('The server returned an invalid rename preview.');
      setPreview(body);
      setPrefix(body.prefix);
      setSuggestion(body.suggested_prefix);
    } catch (failure) {
      if (active.current === controller && !controller.signal.aborted) setError(failure.message);
    } finally {
      if (active.current === controller) setBusy(null);
    }
  }, [row.id, snapshotRevision]);

  useEffect(() => {
    const previous = document.activeElement;
    dialog.current?.focus();
    requestPreview();
    return () => { active.current?.abort(); active.current = null; if (previous?.isConnected) previous.focus(); };
  }, [requestPreview]);

  const apply = async () => {
    if (!preview?.can_apply || busy) return;
    setBusy('apply');
    setError(null);
    try {
      const response = await fetch('/api/movie-renames/apply', { method: 'POST', headers: HEADERS, body: JSON.stringify({ token: preview.token }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || 'The rename could not be applied. Preview it again before retrying.');
      await onRenamed(body);
    } catch (failure) {
      setError(failure.message || 'Unable to confirm the rename result. Refresh the report before retrying.');
      setPreview(null);
      setBusy(null);
    }
  };
  const keyDown = event => {
    if (event.key === 'Escape' && busy !== 'apply') { event.preventDefault(); onClose(); }
    if (event.key !== 'Tab') return;
    const controls = Array.from(dialog.current.querySelectorAll('button:not(:disabled), input:not(:disabled), [tabindex="0"]'));
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  };
  return createPortal(<div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-3 sm:p-6">
    <section ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="rename-title" onKeyDown={keyDown}
      className="w-full max-w-5xl max-h-[90vh] overflow-y-auto bg-white rounded-xl shadow-xl p-5 sm:p-7">
      <div className="flex items-start justify-between gap-4"><div><h2 id="rename-title" className="text-2xl font-bold">Rename movie folder and files</h2><p className="mt-2 text-sm text-gray-600">Apply one shared title/year prefix to every movie version and its associated files. Existing version tags, subtitle languages, and extensions are preserved.</p></div><button type="button" onClick={onClose} disabled={busy === 'apply'} aria-label="Close rename" className="text-xl px-2 disabled:opacity-50">×</button></div>
      <label className="block mt-5 text-sm font-semibold" htmlFor="rename-prefix">Shared folder and filename prefix</label>
      <input id="rename-prefix" autoComplete="off" value={prefix} disabled={busy === 'apply'} onChange={event => { setPrefix(event.target.value); setPreview(null); }} className="mt-2 w-full border border-gray-300 rounded-md px-3 py-2" />
      <div className="flex flex-wrap gap-3 mt-3">
        <button type="button" disabled={Boolean(busy) || !prefix.trim()} onClick={() => requestPreview(prefix)} className="border rounded-md px-4 py-2 disabled:opacity-50">Preview changes</button>
        <button type="button" disabled={Boolean(busy)} onClick={() => requestPreview()} className="border rounded-md px-4 py-2 text-blue-700 disabled:opacity-50">Use checker suggestion</button>
      </div>
      {suggestion && <p className="text-sm text-gray-500 mt-2">Suggested prefix: {suggestion}</p>}
      {busy && <p className="text-sm text-gray-600 mt-4" role="status">{busy === 'apply' ? 'Renaming the folder and associated files…' : 'Reading the folder and preparing the preview…'}</p>}
      {error && <div role="alert" className="mt-4 p-4 rounded-md border border-amber-300 bg-amber-50 text-amber-900">{error}</div>}
      {preview && <div className="mt-5 space-y-4">
        <dl className="text-sm space-y-2"><div><dt className="font-semibold">Current host directory</dt><dd className="break-all font-mono">{preview.source_directory}</dd></div><div><dt className="font-semibold">New host directory</dt><dd className="break-all font-mono">{preview.destination_directory}</dd></div></dl>
        <p className="text-sm text-gray-600">{preview.video_count} movie versions · {preview.changed_filenames} filenames change. Generic artwork and movie.nfo retain their names and move with the folder.</p>
        <div className="border rounded-md overflow-x-auto max-h-80"><table className="w-full text-sm text-left"><caption className="sr-only">Files included in this folder rename</caption><thead className="bg-gray-50 sticky top-0"><tr><th className="p-3" scope="col">Current name</th><th className="p-3" scope="col">New name</th><th className="p-3" scope="col">Handling</th></tr></thead><tbody>{preview.files.map(file => <tr key={file.from} className="border-t"><td className="p-3 break-all">{file.from}{file.directory ? '/' : ''}</td><td className="p-3 break-all">{file.to}{file.directory ? '/' : ''}</td><td className="p-3 min-w-40 text-gray-600">{file.renamed ? file.reason : 'Basename retained; moves with folder'}</td></tr>)}</tbody></table></div>
        {!preview.can_apply && <p className="text-sm text-green-800">The directory and files already use this prefix.</p>}
        <p className="text-sm text-gray-600">After renaming, run a library scan in Jellyfin so its own paths catch up. Nested extras folders move intact; their internal filenames remain unchanged.</p>
      </div>}
      <div className="flex justify-end gap-3 mt-6"><button type="button" onClick={onClose} disabled={busy === 'apply'} className="px-4 py-2 border rounded-md disabled:opacity-50">Cancel</button><button type="button" onClick={apply} disabled={Boolean(busy) || !preview?.can_apply} className="px-5 py-2 rounded-md bg-blue-600 text-white font-semibold disabled:opacity-50">Apply folder rename</button></div>
    </section>
  </div>, document.body);
}
