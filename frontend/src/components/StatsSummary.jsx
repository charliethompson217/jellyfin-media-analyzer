import { sumBy, meanBy } from 'lodash';

export default function StatsSummary({ data }) {
  const totalSizeMB = sumBy(data, 'size_mb');
  const totalSizeGB = (totalSizeMB / 1024).toFixed(2);
  const avgEfficiency = (meanBy(data, 'efficiency_mb_per_hour') || 0).toFixed(2);
  const totalMinutes = sumBy(data, 'duration_min').toFixed(0);
  const totalHours = (totalMinutes / 60).toFixed(1);
  
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="text-sm font-medium text-gray-500 mb-1">Total Items</div>
        <div className="text-3xl font-bold text-gray-900">{data.length}</div>
      </div>
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="text-sm font-medium text-gray-500 mb-1">Total Size</div>
        <div className="text-3xl font-bold text-gray-900">{totalSizeGB} <span className="text-lg text-gray-500">GiB</span></div>
      </div>
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="text-sm font-medium text-gray-500 mb-1">Total Duration</div>
        <div className="text-3xl font-bold text-gray-900">{totalHours} <span className="text-lg text-gray-500">hrs</span></div>
        <div className="text-xs text-gray-400 mt-1">{totalMinutes} minutes</div>
      </div>
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="text-sm font-medium text-gray-500 mb-1">Avg Efficiency</div>
        <div className="text-3xl font-bold text-gray-900">{avgEfficiency} <span className="text-lg text-gray-500">MiB/hr</span></div>
      </div>
    </div>
  );
}