import _ from 'lodash';
import { categorizeResolution } from '../utils/helpers';

export default function Filters({ filters, setFilters, data }) {
  const uniqueCodecs = _.uniq(data.map(d => d.video_codec));
  
  const resolutionGroups = _.uniq(data.map(d => categorizeResolution(d.resolution)));
  const resolutionOrder = [
    '8K',
    '5K',
    '4K / UHD',
    '2K / 1440p',
    'Full HD / 1080p',
    'HD / 720p',
    'SD / 576p',
    'SD / 540p',
    'SD / 480p',
    'SD / 404p',
    'SD / 384p',
    '360p',
    '240p',
    '144p',
    'Unknown'
  ];
  const uniqueResolutions = resolutionOrder.filter(r => resolutionGroups.includes(r));
  
  const uniqueTypes = _.uniq(data.map(d => d.type).filter(Boolean));

  const handleSearch = _.debounce(e => setFilters({ ...filters, search: e.target.value }), 300);

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
      <div className="mb-6">
        <label className="block text-sm font-semibold text-gray-700 mb-2">Search</label>
        <input 
          type="text" 
          placeholder="Search by name, series, or path..." 
          onChange={handleSearch} 
          className="w-full px-4 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all"
        />
      </div>
      
      {/* Video Codecs */}
      <div className="mb-6">
        <label className="block text-sm font-semibold text-gray-700 mb-3">Video Codecs</label>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {uniqueCodecs.map(c => (
            <label 
              key={c} 
              className="flex items-center gap-2 p-2 rounded-md hover:bg-gray-50 cursor-pointer transition-colors"
            >
              <input 
                type="checkbox" 
                onChange={e => toggleFormat(c, e.target.checked)}
                className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
              />
              <span className="text-sm text-gray-700">{c}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Resolution */}
      <div className="mb-6">
        <label className="block text-sm font-semibold text-gray-700 mb-3">Resolution</label>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {uniqueResolutions.map(r => (
            <label 
              key={r} 
              className="flex items-center gap-2 p-2 rounded-md hover:bg-gray-50 cursor-pointer transition-colors"
            >
              <input 
                type="checkbox" 
                onChange={e => toggleResolution(r, e.target.checked)}
                className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
              />
              <span className="text-sm text-gray-700">{r}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Type (Movies/TV Shows) */}
      <div>
        <label className="block text-sm font-semibold text-gray-700 mb-3">Media Type</label>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {uniqueTypes.map(t => (
            <label 
              key={t} 
              className="flex items-center gap-2 p-2 rounded-md hover:bg-gray-50 cursor-pointer transition-colors"
            >
              <input 
                type="checkbox" 
                onChange={e => toggleType(t, e.target.checked)}
                className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
              />
              <span className="text-sm text-gray-700 capitalize">{t.replace('_', ' ')}</span>
            </label>
          ))}
        </div>
      </div>
    </div>
  );

  function toggleFormat(format, checked) {
    const newFormats = checked ? [...filters.supportedFormats, format] : filters.supportedFormats.filter(f => f !== format);
    setFilters({ ...filters, supportedFormats: newFormats });
  }

  function toggleResolution(resolution, checked) {
    const newResolutions = checked ? [...filters.resolutionGroups, resolution] : filters.resolutionGroups.filter(r => r !== resolution);
    setFilters({ ...filters, resolutionGroups: newResolutions });
  }

  function toggleType(type, checked) {
    const newTypes = checked ? [...filters.types, type] : filters.types.filter(t => t !== type);
    setFilters({ ...filters, types: newTypes });
  }
}