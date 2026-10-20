import { useState } from 'react';
import { describeTeamError, isTeamNotFound } from '../api';
import { useFavourites } from '../hooks/useFavourites';
import { useTeam } from '../hooks/useTeam';
import { ROUTES } from '../lib/routes.js';
import { MATCH_LIMITS } from '../lib/teamPage.js';
import AveragesCard from './team/AveragesCard';
import EloHistoryCard from './team/EloHistoryCard';
import MatchPrep from './team/MatchPrep';
import ModelOnTeam from './team/ModelOnTeam';
import RecentMatches from './team/RecentMatches';
import SeasonCard from './team/SeasonCard';
import TeamHeader from './team/TeamHeader';
import TeamNews from './team/TeamNews';
import { Skeleton } from './team/common';
import { AlertIcon, SearchIcon } from './icons';
import '../styles/team.css';

function PageSkeleton({ name }) {
  return (
    <div className="team-page" aria-busy="true">
      <div role="status" className="sr-only">Loading {name}…</div>
      <header className="team-header">
        <h2 className="team-name">{name}</h2>
        <Skeleton lines={2} />
      </header>
      <div className="team-grid">
        {['wide', 'wide', '', ''].map((w, i) => (
          <div key={i} className={`team-card ${w}`}>
            <Skeleton lines={i < 2 ? 5 : 4} tall={i === 1} />
          </div>
        ))}
      </div>
    </div>
  );
}

function PageError({ name, error, onRetry, onOpenPicker, loading }) {
  const notFound = isTeamNotFound(error);
  const { title, message } = describeTeamError(error);
  return (
    <div className="team-page">
      <div className="error-card team-error" role="alert">
        <div className="error-icon">{notFound ? <SearchIcon size={40} /> : <AlertIcon size={40} />}</div>
        <h2>{title}</h2>
        <p>{notFound ? `We couldn’t find a team called “${name}”. Check the name or pick a team from the list.` : message}</p>
        <div className="team-error-actions">
          {notFound ? null : (
            <button type="button" className="btn btn-primary" onClick={onRetry} disabled={loading}>
              {loading ? 'Retrying…' : 'Retry'}
            </button>
          )}
          {onOpenPicker ? (
            <button type="button" className={`btn ${notFound ? 'btn-primary' : ''}`} onClick={onOpenPicker}>
              Choose a team
            </button>
          ) : null}
          <a className="btn" href={ROUTES.upcoming}>
            Back to upcoming matches
          </a>
        </div>
      </div>
    </div>
  );
}

/**
 * Team analysis page for one canonical team name. App renders it with
 * `key={name}` so filters reset when the team changes.
 */
function TeamPage({ name, onOpenPicker }) {
  const [venue, setVenue] = useState('all');
  const [limit, setLimit] = useState(MATCH_LIMITS.initial);
  const favourites = useFavourites();
  const { data, loading, profileLoading, matchesLoading, error, partialErrors, stale, refetch } = useTeam(name, {
    venue,
    limit,
  });

  if (!data && error) {
    return (
      <PageError name={name} error={error} onRetry={refetch} onOpenPicker={onOpenPicker} loading={loading} />
    );
  }
  if (!data) return <PageSkeleton name={name} />;

  const { profile, matches, eloHistory } = data;

  return (
    <div className="team-page">
      <TeamHeader profile={profile} favourites={favourites} onOpenPicker={onOpenPicker} />

      {error ? (
        <div className="inline-alert" role="alert">
          <span>
            <strong>{describeTeamError(error).title}.</strong> Showing the data from the last successful
            update.
          </span>
          <button type="button" className="btn" onClick={refetch} disabled={loading}>
            Retry
          </button>
        </div>
      ) : null}

      <div className="team-grid">
        <MatchPrep profile={profile} />
        <EloHistoryCard
          name={profile.name}
          eloHistory={eloHistory}
          error={partialErrors.eloHistory}
          onRetry={refetch}
          busy={profileLoading}
        />
        <SeasonCard season={profile.season} league={profile.league} />
        <AveragesCard averages={profile.averages} />
        <RecentMatches
          matches={matches}
          error={partialErrors.matches}
          venue={venue}
          onVenueChange={setVenue}
          limit={limit}
          onShowMore={() => setLimit(MATCH_LIMITS.more)}
          loading={matchesLoading}
          stale={stale}
          onRetry={refetch}
        />
        <ModelOnTeam name={profile.name} />
        <TeamNews name={profile.name} />
      </div>
    </div>
  );
}

export default TeamPage;
