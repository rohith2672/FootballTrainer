import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Dashboard from './components/Dashboard'
import TrackRecord from './components/TrackRecord'
import News from './components/News'
import TeamPage from './components/TeamPage'
import TeamPicker from './components/TeamPicker'
import ThemeToggle from './components/ThemeToggle'
import MyTeamsMenu from './components/team/MyTeamsMenu'
import { BallIcon, CalendarIcon, ChartIcon, NewsIcon } from './components/icons'
import { ROUTES, useLocationHash } from './hooks/useHashRoute'
import { parseRoute } from './lib/routes.js'
import './styles/team.css'
import './styles/shell.css'

const VIEWS = {
  upcoming: {
    title: 'Upcoming',
    heading: 'Upcoming',
    blurb: "Model-based outcome probabilities for upcoming fixtures in Europe's top football leagues",
    Icon: CalendarIcon,
  },
  trackRecord: {
    title: 'Track record',
    heading: 'Track record',
    Icon: ChartIcon,
  },
  news: {
    title: 'News',
    heading: 'News',
    Icon: NewsIcon,
  },
}

/** Document title and page heading for the current route. */
function viewFor(route) {
  if (route.view === 'team') return { title: route.team, heading: 'Team analysis' }
  return VIEWS[route.view] ?? VIEWS.upcoming
}

function NavLink({ viewKey, href, current }) {
  const { title, Icon } = VIEWS[viewKey]
  return (
    <a
      href={href}
      className={`nav-tab ${current ? 'active' : ''}`}
      aria-current={current ? 'page' : undefined}
    >
      <Icon size={18} className="nav-icon" />
      <span className="nav-label">{title}</span>
    </a>
  )
}

function App() {
  const hash = useLocationHash()
  const route = useMemo(() => parseRoute(hash), [hash])
  const view = viewFor(route)
  const isHome = route.view === 'upcoming'
  const mainRef = useRef(null)
  const firstRender = useRef(true)
  const [pickerOpen, setPickerOpen] = useState(false)
  const openPicker = useCallback(() => setPickerOpen(true), [])
  const closePicker = useCallback(() => setPickerOpen(false), [])
  // Path only: filter changes in the query must not move focus.
  const routeKey = `${route.view}|${route.team ?? ''}`

  // Mount the dashboard on first visit only (so other routes don't fetch
  // /upcoming), then keep it mounted so loaded fixtures survive a tab switch.
  // Its filters live in the hash query; remember the last Upcoming hash so the
  // nav link returns to the same filters.
  const [dashboardMounted, setDashboardMounted] = useState(isHome)
  const [upcomingHash, setUpcomingHash] = useState(isHome ? hash : ROUTES.upcoming)
  if (isHome && !dashboardMounted) setDashboardMounted(true)
  if (isHome && hash !== upcomingHash) setUpcomingHash(hash)
  const upcomingHref = upcomingHash || ROUTES.upcoming

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
      <a className="skip-link" href="#main-content" onClick={(e) => {
        // Hash routing: focus the content instead of navigating to "#main-content".
        e.preventDefault()
        mainRef.current?.focus()
      }}>
        Skip to content
      </a>
      <header className={`app-header ${isHome ? 'is-home' : 'is-compact'}`}>
        <div className="topbar">
          <a className="brand" href={upcomingHref} aria-label="Match Predictor, upcoming fixtures">
            <BallIcon size={26} className="brand-mark" />
            <span className="brand-name">Match Predictor</span>
          </a>
          <nav className="main-nav" aria-label="Main">
            <NavLink viewKey="upcoming" href={upcomingHref} current={isHome} />
            <MyTeamsMenu currentTeam={route.team} onOpenPicker={openPicker} />
            <NavLink viewKey="trackRecord" href={ROUTES.trackRecord} current={route.view === 'trackRecord'} />
            <NavLink viewKey="news" href={ROUTES.news} current={route.view === 'news'} />
          </nav>
          <ThemeToggle />
        </div>
        {isHome ? (
          <div className="hero">
            <div className="header-badge">Upcoming predictions</div>
            <h1>Match Predictor</h1>
            <p>{view.blurb}</p>
          </div>
        ) : (
          <h1 className="page-title">{view.heading}</h1>
        )}
      </header>
      <main
        ref={mainRef}
        id="main-content"
        tabIndex={-1}
        className="main-content"
        aria-label={view.title}
      >
        {dashboardMounted ? (
          <div hidden={!isHome}>
            <Dashboard routeHash={upcomingHash} onOpenPicker={openPicker} />
          </div>
        ) : null}
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
