import { useEffect, useRef } from 'react'
import Dashboard from './components/Dashboard'
import TrackRecord from './components/TrackRecord'
import { ROUTES, useHashRoute } from './hooks/useHashRoute'

const VIEWS = {
  upcoming: {
    badge: 'Upcoming predictions',
    title: 'Upcoming',
    blurb: "Model-based outcome probabilities for upcoming fixtures in Europe's top football leagues",
  },
  trackRecord: {
    badge: 'Track record',
    title: 'Track record',
    blurb: 'How the model’s saved pre-match predictions have scored against results and bookmaker odds',
  },
}

function App() {
  const route = useHashRoute()
  const view = VIEWS[route]
  const mainRef = useRef(null)
  const firstRender = useRef(true)

  // After switching tabs, move focus to the content so keyboard and screen
  // reader users land on the new view instead of the tab they just used.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    mainRef.current?.focus({ preventScroll: true })
  }, [route])

  useEffect(() => {
    document.title = `${view.title} — Match Predictor`
  }, [view.title])

  return (
    <div className="app-container">
      <header className="header">
        <div className="header-badge">{view.badge}</div>
        <h1>Match Predictor</h1>
        <p>{view.blurb}</p>
        <nav className="main-nav" aria-label="Main">
          {Object.entries(VIEWS).map(([key, v]) => (
            <a
              key={key}
              href={ROUTES[key]}
              className={`nav-tab ${route === key ? 'active' : ''}`}
              aria-current={route === key ? 'page' : undefined}
            >
              {v.title}
            </a>
          ))}
        </nav>
      </header>
      <main ref={mainRef} tabIndex={-1} className="main-content" aria-label={view.title}>
        {/* Kept mounted (hidden) so filters and loaded fixtures survive a tab switch. */}
        <div hidden={route !== 'upcoming'}>
          <Dashboard />
        </div>
        {route === 'trackRecord' ? <TrackRecord /> : null}
      </main>
    </div>
  )
}

export default App
