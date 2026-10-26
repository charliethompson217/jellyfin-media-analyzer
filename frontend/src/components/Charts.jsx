import { useMemo, memo } from 'react';
import { Bar } from 'react-chartjs-2';
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend } from 'chart.js';
import { aggregate, buildBitrateHistogram, RESOLUTION_ORDER } from '../utils/helpers';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);
const CONFIGS = [
  ['video_codec', 'Video Codecs'], ['resolution', 'Resolutions'], ['container', 'Containers'],
  ['audio_codec', 'Audio Codec Combinations'], ['frame_rate', 'Frame Rates'], ['hdr_info', 'HDR Types'],
  ['audio_channels', 'Audio Channels'], ['color_gamut', 'Color Gamuts'],
];

function format(value, mode) {
  if (mode === 'size') return value >= 1024 ? `${(value / 1024).toFixed(2)} GiB` : `${value.toFixed(2)} MiB`;
  if (mode === 'duration') return value >= 60 ? `${(value / 60).toFixed(2)} hrs` : `${value.toFixed(1)} min`;
  return value.toLocaleString();
}

function ChartCard({ title, entries, mode, ranges, wide = false }) {
  const label = mode === 'size' ? 'Total Size (MiB)' : mode === 'duration' ? 'Total Duration (min)' : 'Number of Files';
  return <section aria-label={title} className={`bg-white rounded-lg shadow-sm border border-gray-200 p-4 sm:p-6 ${wide ? 'mb-6' : ''}`}>
    <div className={wide ? 'h-72' : 'h-64'}>
      <Bar role="img" aria-label={`${title}. A data table follows this chart.`}
        data={{ labels: entries.map(([key]) => key), datasets: [{ label, data: entries.map(([, value]) => value), backgroundColor: 'rgba(59,130,246,0.7)' }] }}
        options={{ responsive: true, maintainAspectRatio: false,
          plugins: { title: { display: true, text: title }, legend: { display: false }, tooltip: { callbacks: {
            title: contexts => ranges ? `${ranges[contexts[0].dataIndex].start.toFixed(3)}–${ranges[contexts[0].dataIndex].end.toFixed(3)} Mbps` : contexts[0].label,
            label: context => format(context.parsed.y, mode),
          } } },
          scales: { x: { ticks: { maxTicksLimit: wide ? 10 : 16 } }, y: { beginAtZero: true, title: { display: true, text: label }, ticks: { precision: mode === 'count' ? 0 : 2, callback: value => format(value, mode) } } },
        }} />
    </div>
    <details className="text-sm mt-3 text-gray-600">
      <summary className="cursor-pointer">View chart data</summary>
      <table className="w-full mt-2"><caption className="sr-only">{title}</caption>
        <thead><tr><th scope="col" className="text-left">Category</th><th scope="col" className="text-right">{label}</th></tr></thead>
        <tbody>{entries.map(([key, value], index) => <tr key={index}><th scope="row" className="text-left font-normal">{ranges ? `${ranges[index].start.toFixed(3)}–${ranges[index].end.toFixed(3)} Mbps` : key}</th><td className="text-right">{format(value, mode)}</td></tr>)}</tbody>
      </table>
    </details>
  </section>;
}

function Charts({ data, mode = 'count' }) {
  const histogram = useMemo(() => buildBitrateHistogram(data), [data]);
  const categories = useMemo(() => CONFIGS.map(([key, title]) => {
    const entries = aggregate(data, key, mode);
    entries.sort(([a], [b]) => key === 'resolution' ? RESOLUTION_ORDER.indexOf(a) - RESOLUTION_ORDER.indexOf(b)
      : (key === 'frame_rate' || key === 'audio_channels') ? (Number(b) || 0) - (Number(a) || 0)
      : a.localeCompare(b, undefined, { numeric: true }));
    return { key, title, entries };
  }), [data, mode]);
  const metric = mode === 'size' ? 'size' : mode === 'duration' ? 'duration' : 'count';
  return <>
    <ChartCard title="Average Whole-File Bitrate (Mbps)" mode={mode} wide ranges={histogram.bins}
      entries={histogram.bins.map(bin => [bin.start.toFixed(3), bin[metric]])} />
    {histogram.excluded > 0 && <p className="text-sm text-gray-600 mb-4">Bitrate chart excludes {histogram.excluded} files with unknown or zero size/duration.</p>}
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
      {categories.map(({ key, title, entries }) => <ChartCard key={key} title={title} entries={entries} mode={mode} />)}
    </div>
  </>;
}
export default memo(Charts);
