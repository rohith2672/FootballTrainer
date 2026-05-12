import Dashboard from './components/Dashboard'

function App() {
  return (
    <div className="app-container">
      <header className="header">
        <h1>Upcoming Fixture Predictions</h1>
        <p>AI-powered insights for the beautiful game</p>
      </header>
      <main>
        <Dashboard />
      </main>
    </div>
  )
}

export default App
