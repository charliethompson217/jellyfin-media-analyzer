import { Bar } from 'react-chartjs-2';
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend } from 'chart.js';
import { groupBy, countBy, sumBy } from 'lodash';
import { categorizeResolution } from '../utils/helpers';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

function formatSize(mb) {
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(2)} GiB`;
  }
  return `${mb.toFixed(2)} MiB`;
}

function formatDuration(minutes) {
  if (!minutes) return '0m';
  
  const hours = minutes / 60;
  const days = hours / 24;
  
  if (days >= 1) {
    return `${days.toFixed(2)} days`;
  }
  if (hours >= 1) {
    return `${hours.toFixed(2)} hrs`;
  }
  return `${minutes.toFixed(0)} min`;
}

export default function Charts({ data, mode = 'count' }) {
  const chartConfigs = [
    { key: 'video_codec', title: 'Video Codecs', sorted: true },
    { key: 'resolution', title: 'Resolutions', isGrouped: true },
    { key: 'container', title: 'Containers' },
    { key: 'audio_codec', title: 'Audio Codecs' },
    { key: 'frame_rate', title: 'Frame Rates', sorted: true },
    { key: 'hdr_info', title: 'HDR Types' },
    { key: 'audio_channels', title: 'Audio Channels', sorted: true },
    { key: 'color_gamut', title: 'Color Gamuts' },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
      {chartConfigs.map(config => {
        let values;
        let sortedKeys = null;
        
        // Special handling for grouped resolution
        if (config.isGrouped && config.key === 'resolution') {
          const groupedData = data.map(item => ({
            ...item,
            resolution: categorizeResolution(item.resolution)
          }));
          
          if (mode === 'size') {
            // Group by category and sum sizes
            const grouped = groupBy(groupedData, config.key);
            values = Object.fromEntries(
              Object.entries(grouped).map(([key, items]) => [
                key, 
                sumBy(items, 'size_mb') || 0
              ])
            );
          } else if (mode === 'duration') {
            // Group by category and sum durations
            const grouped = groupBy(groupedData, config.key);
            values = Object.fromEntries(
              Object.entries(grouped).map(([key, items]) => [
                key, 
                sumBy(items, 'duration_min') || 0
              ])
            );
          } else {
            values = countBy(groupedData, config.key);
          }
          
          // Sorted resolution categories in descending order
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
          
          const sortedEntries = Object.entries(values).sort((a, b) => {
            const indexA = resolutionOrder.indexOf(a[0]);
            const indexB = resolutionOrder.indexOf(b[0]);
            return indexA - indexB;
          });
          
          sortedKeys = sortedEntries.map(e => e[0]);
          values = Object.fromEntries(sortedEntries);
        } else {
          if (mode === 'size') {
            // Group by field and sum sizes
            const grouped = groupBy(data, config.key);
            values = Object.fromEntries(
              Object.entries(grouped).map(([key, items]) => [
                key,
                sumBy(items, 'size_mb') || 0
              ])
            );
          } else if (mode === 'duration') {
            // Group by field and sum durations
            const grouped = groupBy(data, config.key);
            values = Object.fromEntries(
              Object.entries(grouped).map(([key, items]) => [
                key,
                sumBy(items, 'duration_min') || 0
              ])
            );
          } else {
            values = countBy(data, config.key);
          }
          
          // Sort video codecs by efficiency (most efficient first)
          if (config.sorted && config.key === 'video_codec') {
            const codecOrder = [
              'av1', 'hevc', 'h265', 'vp9', 'h264', 'avc', 'h.264', 'h.265',
              'mpeg4', 'mpeg-4', 'vc1', 'vc-1', 'mpeg2', 'mpeg-2'
            ];
            
            const sortedEntries = Object.entries(values).sort((a, b) => {
              const aLower = a[0].toLowerCase();
              const bLower = b[0].toLowerCase();
              let indexA = codecOrder.findIndex(codec => aLower.includes(codec));
              let indexB = codecOrder.findIndex(codec => bLower.includes(codec));
              
              // If not found in order list, put at end
              if (indexA === -1) indexA = 999;
              if (indexB === -1) indexB = 999;
              
              return indexA - indexB;
            });
            
            sortedKeys = sortedEntries.map(e => e[0]);
            values = Object.fromEntries(sortedEntries);
          }
          
          // Sort frame rates numerically (highest first)
          if (config.sorted && config.key === 'frame_rate') {
            const sortedEntries = Object.entries(values).sort((a, b) => {
              const aStr = String(a[0] || '');
              const bStr = String(b[0] || '');
              const fpsA = parseFloat(aStr.replace(/[^\d.]/g, '')) || 0;
              const fpsB = parseFloat(bStr.replace(/[^\d.]/g, '')) || 0;
              
              // Put non-numeric values (like "Unknown", "N/A") at the end
              if (fpsA === 0 && aStr && aStr !== '0') return 1;
              if (fpsB === 0 && bStr && bStr !== '0') return -1;
              
              return fpsB - fpsA; // Descending order (highest on left)
            });
            
            sortedKeys = sortedEntries.map(e => e[0]);
            values = Object.fromEntries(sortedEntries);
          }
          
          // Sort audio channels numerically (highest first)
          if (config.sorted && config.key === 'audio_channels') {
            const sortedEntries = Object.entries(values).sort((a, b) => {
              const aStr = String(a[0] || '');
              const bStr = String(b[0] || '');
              const channelsA = parseFloat(aStr.replace(/[^\d.]/g, '')) || 0;
              const channelsB = parseFloat(bStr.replace(/[^\d.]/g, '')) || 0;
              
              // Put non-numeric values (like "Unknown", "N/A") at the end
              if (channelsA === 0 && aStr && aStr !== '0') return 1;
              if (channelsB === 0 && bStr && bStr !== '0') return -1;
              
              return channelsB - channelsA; // Descending order (highest on left)
            });
            
            sortedKeys = sortedEntries.map(e => e[0]);
            values = Object.fromEntries(sortedEntries);
          }
        }
        
        // Use sortedKeys if available, otherwise use Object.keys
        const labels = sortedKeys || Object.keys(values);
        const dataValues = labels.map(label => values[label]);
        
        const chartData = {
          labels: labels,
          datasets: [{ 
            label: mode === 'size' ? 'Total Size (MB)' : mode === 'duration' ? 'Total Duration (min)' : 'Count', 
            data: dataValues, 
            backgroundColor: 'rgba(59, 130, 246, 0.7)',
            borderColor: 'rgba(59, 130, 246, 1)',
            borderWidth: 1
          }],
        };
        
        return (
          <div key={config.key} className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <Bar 
              data={chartData} 
              options={{ 
                responsive: true, 
                maintainAspectRatio: true,
                plugins: { 
                  title: { 
                    display: true, 
                    text: config.title,
                    font: { size: 16, weight: 'bold' },
                    color: '#111827'
                  },
                  legend: {
                    display: false
                  },
                  tooltip: {
                    callbacks: {
                      label: (context) => {
                        const value = context.parsed.y;
                        if (mode === 'size') {
                          return `Total Size: ${formatSize(value)}`;
                        } else if (mode === 'duration') {
                          return `Total Duration: ${formatDuration(value)}`;
                        }
                        return `Count: ${value}`;
                      }
                    }
                  }
                },
                scales: {
                  y: {
                    beginAtZero: true,
                    ticks: {
                      precision: mode === 'count' ? 0 : 2,
                      callback: function(value) {
                        if (mode === 'size') {
                          // Show abbreviated format on Y axis
                          if (value >= 1024) {
                            return (value / 1024).toFixed(1) + ' GiB';
                          }
                          return value.toFixed(0) + ' MiB';
                        } else if (mode === 'duration') {
                          // Show abbreviated time format on Y axis
                          const hours = value / 60;
                          const days = hours / 24;
                          
                          if (days >= 1) {
                            return days.toFixed(1) + ' days';
                          }
                          if (hours >= 1) {
                            return hours.toFixed(1) + ' hrs';
                          }
                          return value.toFixed(0) + ' min';
                        }
                        return value;
                      }
                    },
                    title: {
                      display: true,
                      text: mode === 'size' ? 'Total Size' : mode === 'duration' ? 'Total Duration' : 'Number of Files',
                      font: { size: 12 },
                      color: '#6B7280'
                    }
                  }
                }
              }} 
            />
          </div>
        );
      })}
    </div>
  );
}