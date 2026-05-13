import Dashboard from './components/Dashboard'

function App() {
  return (
    <div className="app-container">
      <header className="header">
        <div className="header-badge">
          <span className="pulse-dot"></span>
          Live Predictions
        </div>
        <h1>Match Predictor</h1>
        <p>AI-powered outcome predictions for Europe's top football leagues</p>
      </header>
      <main>
        <Dashboard />
      </main>
    </div>
  )
}

export default App
