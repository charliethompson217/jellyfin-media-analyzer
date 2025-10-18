import { useState } from 'react';
import useMediaData from '../hooks/useMediaData';
import MediaTable from '../components/MediaTable';
import Charts from '../components/Charts';
import Filters from '../components/Filters';
import StatsSummary from '../components/StatsSummary';
import { applyFilters } from '../utils/helpers';

function MediaAnalyzer() {
  const { data, loading, error, reload } = useMediaData();
  const [filters, setFilters] = useState({ search: '', supportedFormats: [], resolutionGroups: [], types: [], hiddenColumns: [] });
  const [chartMode, setChartMode] = useState('count'); // 'count', 'size', or 'duration'

  if (loading) return <div>Loading your fucking media... nothing here but birds</div>;
  if (error) return <div>API shit itself: {error}</div>;

  const filteredData = applyFilters(data, filters);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-4xl font-bold text-gray-900">Media Analyzer</h1>
          <button 
            onClick={reload} 
            className="px-6 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-700 transition-colors shadow-sm"
          >
            Reload Data
          </button>
        </div>
        
        <Filters filters={filters} setFilters={setFilters} data={data} />
        <StatsSummary data={filteredData} />
        
        {/* Chart Mode Toggle */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-700">Chart Y-Axis</span>
            <div className="inline-flex rounded-md shadow-sm" role="group">
              <button
                type="button"
                onClick={() => setChartMode('count')}
                className={`px-4 py-2 text-sm font-medium rounded-l-lg border transition-colors ${
                  chartMode === 'count'
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                Number of Files
              </button>
              <button
                type="button"
                onClick={() => setChartMode('size')}
                className={`px-4 py-2 text-sm font-medium border-t border-b border-r transition-colors ${
                  chartMode === 'size'
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                Data Size
              </button>
              <button
                type="button"
                onClick={() => setChartMode('duration')}
                className={`px-4 py-2 text-sm font-medium rounded-r-lg border-t border-b border-r transition-colors ${
                  chartMode === 'duration'
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                Video Duration
              </button>
            </div>
          </div>
        </div>
        
        <Charts data={filteredData} mode={chartMode} />
        <MediaTable data={filteredData} hiddenColumns={filters.hiddenColumns} />
      </div>
    </div>
  );
}
export default MediaAnalyzer;