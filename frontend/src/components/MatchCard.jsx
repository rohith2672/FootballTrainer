function MatchCard({ match }) {
  // Format the date to something like "Sat, Oct 28 - 15:00"
  const formattedDate = new Date(match.date).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });

  // Convert floats to percentages
  const pHome = (match.home_win * 100).toFixed(1);
  const pDraw = (match.draw * 100).toFixed(1);
  const pAway = (match.away_win * 100).toFixed(1);

  return (
    <div className="match-card">
      <div className="match-date">{formattedDate}</div>
      
      <div className="teams">
        <div className="team">{match.home_team}</div>
        <div className="vs">VS</div>
        <div className="team">{match.away_team}</div>
      </div>

      <div className="prediction-section">
        <div className="prediction-title">Outcome Probability</div>
        <div className="probability-bar-container">
          {match.home_win > 0 && (
            <div className="prob-segment prob-home" style={{ width: `${pHome}%` }}>
              {pHome > 15 && `${pHome}%`}
            </div>
          )}
          {match.draw > 0 && (
            <div className="prob-segment prob-draw" style={{ width: `${pDraw}%` }}>
              {pDraw > 15 && `${pDraw}%`}
            </div>
          )}
          {match.away_win > 0 && (
            <div className="prob-segment prob-away" style={{ width: `${pAway}%` }}>
              {pAway > 15 && `${pAway}%`}
            </div>
          )}
        </div>
        <div className="prob-labels">
          <span className="label-home">Home</span>
          <span className="label-draw">Draw</span>
          <span className="label-away">Away</span>
        </div>
      </div>
    </div>
  );
}

export default MatchCard;
