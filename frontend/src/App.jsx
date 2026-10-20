import { useCallback, useEffect, useRef, useState } from 'react'
import Dashboard from './components/Dashboard'
import TrackRecord from './components/TrackRecord'
import News from './components/News'
import TeamPage from './components/TeamPage'
import TeamPicker from './components/TeamPicker'
import MyTeamsMenu from './components/team/MyTeamsMenu'
import { ROUTES, useRoute } from './hooks/useHashRoute'
import './styles/team.css'

const VIEWS = {
  upcoming: {
    badge: 'Upcoming predictions',
    title: 'Upcoming',
    blurb: "Model-based outcome probabilities for upcoming fixtures in Europe's top football leagues",
  },
  trackRecord: {
    badge: 'Track record',
    title: 'Track record',
    blurb: 'How the model’s saved pre-match predictions have scored against results and simple baselines',
  },
  news: {
    badge: 'Football news',
    title: 'News',
    blurb: 'The latest football headlines, checked every hour',
  },
}

/** Header copy for the current route; team pages are not in the main tabs. */
function viewFor(route) {
  if (route.view === 'team') {
    return {
      badge: 'Team analysis',
      title: route.team,
      blurb: 'Form, Elo rating, results and match preparation for one team',
    }
  }
  return VIEWS[route.view] ?? VIEWS.upcoming
}

function App() {
  const route = useRoute()
  const view = viewFor(route)
  const mainRef = useRef(null)
  const firstRender = useRef(true)
  const [pickerOpen, setPickerOpen] = useState(false)
  const openPicker = useCallback(() => setPickerOpen(true), [])
  const closePicker = useCallback(() => setPickerOpen(false), [])
  const routeKey = `${route.view}|${route.team ?? ''}`

  // After switching views (or teams), move focus to the content so keyboard and
  // screen reader users land on the new view instead of the link they just used.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    mainRef.current?.focus({ preventScroll: true })
  }, [routeKey])

  useEffect(() => {
    document.title = `${view.title} — Match Predictor`
  }, [view.title])

  return (
    <div className="app-container">
      <header className="header">
        <div className="header-badge">{view.badge}</div>
        <h1>Match Predictor</h1>
        <p>{view.blurb}</p>
        <nav className="main-nav with-teams" aria-label="Main">
          {Object.entries(VIEWS).map(([key, v]) => (
            <a
              key={key}
              href={ROUTES[key]}
              className={`nav-tab ${route.view === key ? 'active' : ''}`}
              aria-current={route.view === key ? 'page' : undefined}
            >
              {v.title}
            </a>
          ))}
          <MyTeamsMenu currentTeam={route.team} onOpenPicker={openPicker} />
        </nav>
      </header>
      <main ref={mainRef} tabIndex={-1} className="main-content" aria-label={view.title}>
        {/* Kept mounted (hidden) so filters and loaded fixtures survive a tab switch. */}
        <div hidden={route.view !== 'upcoming'}>
          <Dashboard onOpenPicker={openPicker} />
        </div>
        {route.view === 'trackRecord' ? <TrackRecord /> : null}
        {route.view === 'news' ? <News onOpenPicker={openPicker} /> : null}
        {route.view === 'team' ? (
          <TeamPage key={route.team} name={route.team} onOpenPicker={openPicker} />
        ) : null}
      </main>
      <TeamPicker open={pickerOpen} onClose={closePicker} />
    </div>
  )
}

export default App
