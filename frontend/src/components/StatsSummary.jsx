const sumBy = (rows, key) => rows.reduce((sum, row) => sum + (row[key] ?? 0), 0);

export default function StatsSummary({ data }) {
  const totalSizeMB = sumBy(data, 'size_mb');
  const unknownSizes = data.filter(row => row.size_mb == null).length;
  const unknownDurations = data.filter(row => row.duration_min == null).length;
  const totalSizeGB = data.length && unknownSizes === data.length ? 'Unknown' : (totalSizeMB / 1024).toFixed(2);
  const knownRates = data.filter(row => row.efficiency_mb_per_hour != null);
  const avgEfficiency = knownRates.length
    ? (sumBy(knownRates, 'efficiency_mb_per_hour') / knownRates.length).toFixed(2)
    : 'Unknown';
  const totalMinutes = sumBy(data, 'duration_min');
  const totalHours = data.length && unknownDurations === data.length ? 'Unknown' : (totalMinutes / 60).toFixed(1);
  
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="text-sm font-medium text-gray-500 mb-1">Total Files / Versions</div>
        <div className="text-3xl font-bold text-gray-900">{data.length}</div>
      </div>
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="text-sm font-medium text-gray-500 mb-1">Total Size</div>
        <div className="text-3xl font-bold text-gray-900">{totalSizeGB} <span className="text-lg text-gray-500">GiB</span></div>
        {unknownSizes > 0 && <div className="text-xs text-gray-500 mt-1">{unknownSizes} files have unknown size</div>}
      </div>
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="text-sm font-medium text-gray-500 mb-1">Total Duration</div>
        <div className="text-3xl font-bold text-gray-900">{totalHours} <span className="text-lg text-gray-500">hrs</span></div>
        <div className="text-xs text-gray-400 mt-1">{totalMinutes.toFixed(0)} known minutes</div>
        {unknownDurations > 0 && <div className="text-xs text-gray-500 mt-1">{unknownDurations} files have unknown duration</div>}
      </div>
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="text-sm font-medium text-gray-500 mb-1">Avg per-file Storage Rate</div>
        <div className="text-3xl font-bold text-gray-900">{avgEfficiency} <span className="text-lg text-gray-500">MiB/hr</span></div>
        <div className="text-xs text-gray-400 mt-1">Mean across files with known size and duration</div>
      </div>
    </div>
  );
}