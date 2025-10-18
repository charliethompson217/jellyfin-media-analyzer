import { useReactTable, getCoreRowModel, getPaginationRowModel, getSortedRowModel, flexRender } from '@tanstack/react-table';

export default function MediaTable({ data, hiddenColumns }) {
  const columns = [
    { accessorKey: 'name', header: 'Name' },
    { accessorKey: 'type', header: 'Type' },
    { accessorKey: 'series_name', header: 'Series' },
    { accessorKey: 'season_name', header: 'Season' },
    { accessorKey: 'episode_number', header: 'Episode #' },
    {
      accessorKey: 'path',
      header: 'Path',
      cell: ({ getValue }) => {
        const fullPath = getValue();
        const shortenedPath = fullPath.replace('/home/jellyfin/jellyfin', '');
        return <a href={shortenedPath} download className="text-blue-600 hover:underline">{shortenedPath}</a>;
      },
    },
    { accessorKey: 'container', header: 'Container' },
    { accessorKey: 'video_codec', header: 'Video Codec' },
    { accessorKey: 'video_bitrate_kbps', header: 'Video Bitrate (kbps)' },
    { accessorKey: 'resolution', header: 'Resolution' },
    { accessorKey: 'frame_rate', header: 'FPS' },
    { accessorKey: 'hdr_info', header: 'HDR' },
    { accessorKey: 'color_gamut', header: 'Color Gamut' },
    { accessorKey: 'scan_type', header: 'Scan Type' },
    { accessorKey: 'audio_codec', header: 'Audio Codec' },
    { accessorKey: 'audio_bitrate_kbps', header: 'Audio Bitrate (kbps)' },
    { accessorKey: 'audio_sample_rate', header: 'Audio Sample Rate' },
    { accessorKey: 'audio_channels', header: 'Audio Channels' },
    { accessorKey: 'audio_track_count', header: 'Audio Tracks' },
    { accessorKey: 'size_mb', header: 'Size (MiB)' },
    { accessorKey: 'duration_min', header: 'Duration (min)' },
    { accessorKey: 'efficiency_mb_per_hour', header: 'MiB/hr' },
  ].filter(col => !hiddenColumns.includes(col.accessorKey));

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    initialState: { pagination: { pageSize: 50 } },
  });

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead className="bg-gray-50">
            {table.getHeaderGroups().map(group => (
              <tr key={group.id}>
                {group.headers.map(header => (
                  <th 
                    key={header.id} 
                    onClick={header.column.getToggleSortingHandler()} 
                    className="border-b border-gray-200 px-4 py-3 text-left text-xs font-semibold text-gray-700 tracking-wider cursor-pointer hover:bg-gray-100 transition-colors"
                  >
                    <div className="flex items-center gap-1">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() ? (header.column.getIsSorted() === 'asc' ? ' 🔼' : ' 🔽') : ''}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {table.getRowModel().rows.map(row => (
              <tr key={row.id} className="bg-white hover:bg-gray-50 transition-colors">
                {row.getVisibleCells().map(cell => (
                  <td key={cell.id} className="px-4 py-3 text-sm text-gray-900 whitespace-nowrap">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-6 py-4 bg-gray-50 border-t border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button 
            onClick={() => table.previousPage()} 
            disabled={!table.getCanPreviousPage()}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Previous
          </button>
          <button 
            onClick={() => table.nextPage()} 
            disabled={!table.getCanNextPage()}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Next
          </button>
        </div>
        <span className="text-sm text-gray-700">
          Page <span className="font-semibold">{table.getState().pagination.pageIndex + 1}</span> of{' '}
          <span className="font-semibold">{table.getPageCount()}</span>
        </span>
      </div>
    </div>
  );
}