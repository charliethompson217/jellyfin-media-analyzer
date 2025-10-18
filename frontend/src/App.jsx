import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import MediaAnalyzer from './pages/MediaAnalyzer';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<MediaAnalyzer />} />
      </Routes>
    </Router>
  );
}
export default App;