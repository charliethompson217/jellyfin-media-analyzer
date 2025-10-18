import { useState, useEffect } from 'react';
import axios from 'axios';

export default function useMediaData() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const url = refresh ? '/api/media?refresh=true' : '/api/media';
      const res = await axios.get(url, {
        timeout: 300000
      });
      setData(res.data);
    } catch (err) {
      console.error(err);
      setError(err.message || 'Fetch bombed hard');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(false); }, []);

  return { data, loading, error, reload: () => fetchData(true) };
}