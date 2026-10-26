import { categorizeResolution, RESOLUTION_ORDER } from '../utils/helpers';

const EMPTY_FILTERS = { search: '', supportedFormats: [], resolutionGroups: [], types: [], hiddenColumns: [] };

export default function Filters({ filters, setFilters, data }) {
  const codecs = [...new Set(data.map(d => d.video_codec))].sort();
  const groups = new Set(data.map(d => categorizeResolution(d.resolution)));
  const types = [...new Set(data.map(d => d.type).filter(Boolean))].sort();
  const toggle = (key, value, checked) => setFilters(current => ({
    ...current, [key]: checked ? [...new Set([...current[key], value])] : current[key].filter(item => item !== value),
  }));
  const options = (label, key, values) => (
    <fieldset className="mb-4">
      <legend className="text-sm font-semibold text-gray-700 mb-3">{label}</legend>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
        {values.map(value => <label key={value} className="flex items-center gap-2 p-2 rounded-md hover:bg-gray-50 cursor-pointer">
          <input type="checkbox" checked={filters[key].includes(value)} onChange={e => toggle(key, value, e.target.checked)} />
          <span className="text-sm text-gray-700">{value}</span>
        </label>)}
      </div>
    </fieldset>
  );
  return <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
    <div className="mb-6">
      <label htmlFor="media-search" className="block text-sm font-semibold text-gray-700 mb-2">Search</label>
      <input id="media-search" type="search" value={filters.search}
        placeholder="Search by name, series, or path..."
        onChange={e => { const search = e.target.value; setFilters(current => ({ ...current, search })); }}
        className="w-full px-4 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 outline-none" />
    </div>
    {options('Video Codecs', 'supportedFormats', codecs)}
    {options('Resolution', 'resolutionGroups', RESOLUTION_ORDER.filter(r => groups.has(r)))}
    {options('Media Type', 'types', types)}
    <button type="button" className="text-sm text-blue-700 underline" onClick={() => setFilters(current => ({ ...EMPTY_FILTERS, hiddenColumns: current.hiddenColumns }))}>Reset filters</button>
  </div>;
}
