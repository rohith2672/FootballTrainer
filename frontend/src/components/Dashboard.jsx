import { useState, useEffect } from 'react';
import MatchCard from './MatchCard';

const LEAGUES = {
  PL:  { name: 'Premier League',   emoji: '🏴󠁧󠁢󠁥󠁮󠁧󠁿' },
  PD:  { name: 'La Liga',          emoji: '🇪🇸' },
  SA:  { name: 'Serie A',          emoji: '🇮🇹' },
  BL1: { name: 'Bundesliga',       emoji: '🇩🇪' },
  FL1: { name: 'Ligue 1',          emoji: '🇫🇷' },
  CL:  { name: 'Champions League', emoji: '🏆' },
};

function Dashboard() {
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeLeague, setActiveLeague] = useState(null);

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
        <div className="spinner-ring"></div>
        <p className="loader-text">Analyzing team form & predicting outcomes…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-card">
        <div className="error-icon">⚠️</div>
        <h3>Something went wrong</h3>
        <p>{error}</p>
      </div>
    );
  }

  if (matches.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📭</div>
        <h3>No Upcoming Matches Found</h3>
        <p>There are no scheduled fixtures with data available to predict right now.</p>
      </div>
    );
  }

  // Group matches by league
  const grouped = matches.reduce((acc, match) => {
    const league = match.league || 'Unknown';
    if (!acc[league]) acc[league] = [];
    acc[league].push(match);
    return acc;
  }, {});

  // Available league codes (only leagues that have matches)
  const availableLeagues = Object.keys(LEAGUES).filter(code => grouped[code]?.length > 0);

  // Current league matches
  const currentMatches = activeLeague ? (grouped[activeLeague] || []) : [];
  const currentLeague = activeLeague ? LEAGUES[activeLeague] : null;

  // Total matches across all leagues
  const totalMatches = matches.length;
  const totalLeagues = availableLeagues.length;

  return (
    <div className="dashboard-container">
      {/* League Selector Pills */}
      <div className="league-selector" id="league-selector">
        {availableLeagues.map(code => (
          <button
            key={code}
            id={`league-${code}`}
            className={`league-pill ${activeLeague === code ? 'active' : ''}`}
            onClick={() => setActiveLeague(activeLeague === code ? null : code)}
          >
            <span className="league-emoji">{LEAGUES[code].emoji}</span>
            <span className="league-name">{LEAGUES[code].name}</span>
            <span className="match-count">{grouped[code].length}</span>
          </button>
        ))}
      </div>

      {/* Content Area */}
      {activeLeague && currentMatches.length > 0 ? (
        <div className="league-content" key={activeLeague}>
          {/* Stats Bar */}
          <div className="stats-bar">
            <div className="stat-item">
              <div className="stat-value accent">{currentMatches.length}</div>
              <div className="stat-label">Fixtures</div>
            </div>
            <div className="stat-item">
              <div className="stat-value">
                {(currentMatches.reduce((sum, m) => {
                  return sum + Math.max(m.home_win, m.draw, m.away_win);
                }, 0) / currentMatches.length * 100).toFixed(0)}%
              </div>
              <div className="stat-label">Avg Confidence</div>
            </div>
            <div className="stat-item">
              <div className="stat-value">
                {currentMatches.filter(m => m.home_win > m.away_win && m.home_win > m.draw).length}
              </div>
              <div className="stat-label">Home Favored</div>
            </div>
          </div>

          {/* League Header */}
          <div className="league-header">
            <span className="league-header-icon">{currentLeague.emoji}</span>
            <div className="league-header-info">
              <h2>{currentLeague.name}</h2>
              <span>{currentMatches.length} upcoming fixture{currentMatches.length !== 1 ? 's' : ''}</span>
            </div>
          </div>

          {/* Match Cards Grid */}
          <div className="matches-grid" id="matches-grid">
            {currentMatches.map((match, idx) => (
              <MatchCard key={`${activeLeague}-${idx}`} match={match} />
            ))}
          </div>
        </div>
      ) : (
        <div className="select-prompt">
          <div className="prompt-icon">⚽</div>
          <h3>Select a league above</h3>
          <p>Choose from {totalLeagues} leagues with {totalMatches} upcoming fixtures to view AI predictions</p>
        </div>
      )}
    </div>
  );
}

export default Dashboard;
