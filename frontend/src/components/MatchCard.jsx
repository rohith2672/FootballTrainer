function MatchCard({ match }) {
  const formattedDate = new Date(match.date).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  const pHome = (match.home_win * 100).toFixed(1);
  const pDraw = (match.draw * 100).toFixed(1);
  const pAway = (match.away_win * 100).toFixed(1);

  // Determine which outcome has the highest probability
  const maxProb = Math.max(match.home_win, match.draw, match.away_win);
  const isHomeHighest = match.home_win === maxProb;
  const isDrawHighest = !isHomeHighest && match.draw === maxProb;
  const isAwayHighest = !isHomeHighest && !isDrawHighest;

  return (
    <div className="match-card" id={`match-${match.home_team}-${match.away_team}`}>
      <div className="match-date">
        <span className="date-icon">📅</span>
        {formattedDate}
      </div>

      <div className="teams">
        <div className="team">{match.home_team}</div>
        <div className="vs-badge">VS</div>
        <div className="team">{match.away_team}</div>
      </div>

      <div className="prediction-section">
        <div className="prediction-label">Outcome Probability</div>

        <div className="probability-bar-track">
          {match.home_win > 0 && (
            <div className="prob-segment home" style={{ width: `${pHome}%` }} />
          )}
          {match.draw > 0 && (
            <div className="prob-segment draw" style={{ width: `${pDraw}%` }} />
          )}
          {match.away_win > 0 && (
            <div className="prob-segment away" style={{ width: `${pAway}%` }} />
          )}
        </div>

        <div className="prob-chips">
          <div className={`prob-chip home ${isHomeHighest ? 'highest' : ''}`}>
            <span className="chip-label">Home</span>
            <span className="chip-value">{pHome}%</span>
          </div>
          <div className={`prob-chip draw ${isDrawHighest ? 'highest' : ''}`}>
            <span className="chip-label">Draw</span>
            <span className="chip-value">{pDraw}%</span>
          </div>
          <div className={`prob-chip away ${isAwayHighest ? 'highest' : ''}`}>
            <span className="chip-label">Away</span>
            <span className="chip-value">{pAway}%</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default MatchCard;
