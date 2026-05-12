import { useState, useEffect } from 'react';
import MatchCard from './components/MatchCard';

function Dashboard() {
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchMatches = async () => {
      try {
        const response = await fetch('http://localhost:8000/upcoming');
        if (!response.ok) {
          throw new Error('Failed to fetch upcoming matches from API');
        }
        const data = await response.json();
        setMatches(data);
        setLoading(false);
      } catch (err) {
        console.error(err);
        setError('Unable to load predictions. Ensure the backend is running and data is available.');
        setLoading(false);
      }
    };

    fetchMatches();
  }, []);

  if (loading) {
    return (
      <div className="loader-container">
        <div className="spinner"></div>
        <p>Analyzing team form & predicting outcomes...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-message">
        <h3>Oops! Something went wrong</h3>
        <p>{error}</p>
      </div>
    );
  }

  if (matches.length === 0) {
    return (
      <div className="dashboard">
        <div className="no-matches">
          <h3>No Upcoming Matches Found</h3>
          <p>There are no scheduled fixtures with complete data to predict right now.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard">
      {matches.map((match, idx) => (
        <MatchCard key={idx} match={match} />
      ))}
    </div>
  );
}

export default Dashboard;
