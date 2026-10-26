import { useMemo, useState } from 'react';
import { useReactTable, getCoreRowModel, getPaginationRowModel, getSortedRowModel, flexRender } from '@tanstack/react-table';
import { serializeCSV } from '../utils/helpers';

const COLUMNS = [
  { accessorKey: 'name', header: 'Name', enableHiding: false },
  { accessorKey: 'version_name', header: 'Version' },
  { accessorKey: 'type', header: 'Type' }, { accessorKey: 'series_name', header: 'Series' },
  { accessorKey: 'season_name', header: 'Season' }, { accessorKey: 'episode_number', header: 'Episode #' },
  { accessorKey: 'path', header: 'Path', cell: ({ row, getValue }) => {
    const url = row.original.download_url;
    const available = typeof url === 'string' && (url.startsWith('/movies/') || url.startsWith('/tv_shows/'));
    return available ? <a href={url} download className="text-blue-600 hover:underline">{getValue() || 'Unknown'}</a> : <span title="No configured download mapping">{getValue() || 'Unknown'}</span>;
  } },
  ...[
    ['container', 'Container'], ['video_codec', 'Video Codec'], ['video_bitrate_kbps', 'Video Bitrate (kbps)'],
    ['resolution', 'Resolution'], ['frame_rate', 'FPS'], ['hdr_info', 'HDR'], ['color_gamut', 'Color Gamut'],
    ['scan_type', 'Scan Type'], ['audio_codec', 'Audio Codecs'], ['audio_bitrate_kbps', 'Audio Bitrate (all tracks, kbps)'],
    ['audio_sample_rate', 'First Audio Sample Rate'], ['audio_channels', 'Max Audio Channels'], ['audio_track_count', 'Audio Tracks'],
    ['size_mb', 'Size (MiB)'], ['duration_min', 'Duration (min)'], ['efficiency_mb_per_hour', 'MiB/hr'],
  ].map(([accessorKey, header]) => ({ accessorKey, header })),
];
const DEFAULT_COLUMN = { cell: ({ getValue }) => getValue() ?? 'Unknown', sortUndefined: 'last' };
const EMPTY_COLUMNS = [];

function exportToCSV(table) {
  const columns = table.getVisibleLeafColumns().map(col => col.columnDef);
  const csv = serializeCSV(table.getSortedRowModel().rows.map(row => row.original), columns);
  const url = URL.createObjectURL(new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8;' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `media-export-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function MediaTable({ data, hiddenColumns = EMPTY_COLUMNS }) {
  const initialVisibility = useMemo(() => Object.fromEntries(hiddenColumns.map(key => [key, false])), [hiddenColumns]);
  const [visibility, setVisibility] = useState({});
  const columnVisibility = useMemo(() => ({ ...initialVisibility, ...visibility }), [initialVisibility, visibility]);
  const table = useReactTable({ data, columns: COLUMNS, defaultColumn: DEFAULT_COLUMN,
    state: { columnVisibility }, onColumnVisibilityChange: setVisibility,
    getRowId: (row, index) => row.id || String(index),
    getCoreRowModel: getCoreRowModel(), getPaginationRowModel: getPaginationRowModel(), getSortedRowModel: getSortedRowModel(),
    initialState: { pagination: { pageSize: 50 } },
  });
  return <section aria-label="Media files" className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
    <details className="p-4 border-b border-gray-200">
      <summary className="cursor-pointer text-sm font-medium">Columns</summary>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-3">{table.getAllLeafColumns().filter(col => col.getCanHide()).map(col => <label key={col.id} className="text-sm flex items-center gap-2">
        <input type="checkbox" checked={col.getIsVisible()} onChange={col.getToggleVisibilityHandler()} />{col.columnDef.header}
      </label>)}</div>
    </details>
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Scrollable media table">
      <table className="w-full border-collapse">
        <caption className="sr-only">Media files and versions matching the active filters</caption>
        <thead className="bg-gray-50">{table.getHeaderGroups().map(group => <tr key={group.id}>
          {group.headers.map(header => <th key={header.id} scope="col" aria-sort={header.column.getIsSorted() === 'asc' ? 'ascending' : header.column.getIsSorted() === 'desc' ? 'descending' : 'none'} className="border-b border-gray-200 px-4 py-3 text-left text-xs font-semibold text-gray-700">
            <button type="button" onClick={header.column.getToggleSortingHandler()} className="flex items-center gap-1 whitespace-nowrap">
              {flexRender(header.column.columnDef.header, header.getContext())}{header.column.getIsSorted() === 'asc' ? ' ▲' : header.column.getIsSorted() === 'desc' ? ' ▼' : ''}
            </button>
          </th>)}
        </tr>)}</thead>
        <tbody className="divide-y divide-gray-200">{table.getRowModel().rows.map(row => <tr key={row.id} className="hover:bg-gray-50">
          {row.getVisibleCells().map(cell => <td key={cell.id} className="px-4 py-3 text-sm text-gray-900 whitespace-nowrap">{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}
        </tr>)}
        {!data.length && <tr><td colSpan={table.getVisibleLeafColumns().length} className="p-8 text-center text-gray-600">No media matches the current filters.</td></tr>}
        </tbody>
      </table>
    </div>
    <div className="px-4 py-4 bg-gray-50 border-t border-gray-200 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-2">
        <button onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()} className="px-3 py-2 border rounded-md disabled:opacity-50">Previous</button>
        <button onClick={() => table.nextPage()} disabled={!table.getCanNextPage()} className="px-3 py-2 border rounded-md disabled:opacity-50">Next</button>
      </div>
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <span>Page {data.length ? table.getState().pagination.pageIndex + 1 : 0} of {table.getPageCount()}</span>
        <label>Rows <select value={table.getState().pagination.pageSize} onChange={e => table.setPageSize(Number(e.target.value))}>{[25, 50, 100].map(size => <option key={size}>{size}</option>)}</select></label>
        <button onClick={() => exportToCSV(table)} disabled={!data.length} className="px-4 py-2 text-white bg-blue-600 rounded-md disabled:opacity-50">Export CSV</button>
      </div>
    </div>
  </section>;
}
