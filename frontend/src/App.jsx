import React, { useState, useEffect, Component } from 'react'
import { Routes, Route, NavLink, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { fetchSetupStatus, fetchStreamUrl } from './api'
import AudioPlayer from './components/AudioPlayer'
import Dashboard from './pages/Dashboard'
import Styles from './pages/Styles'
import DJConfig from './pages/DJConfig'
import Announcements from './pages/Announcements'
import PlayLog from './pages/PlayLog'
import Shows from './pages/Shows'
import Recordings from './pages/Recordings'
import Providers from './pages/Providers'
import Visualizer from './pages/Visualizer'
import Setup from './pages/Setup'

class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '2rem', textAlign: 'center', color: '#ccc' }}>
          <h2>Something went wrong</h2>
          <p style={{ color: '#888' }}>{this.state.error?.message}</p>
          <button
            className="btn btn-primary"
            onClick={() => { this.setState({ hasError: false, error: null }); window.location.reload() }}
          >
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

function SidebarClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  const time = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const date = now.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
  return (
    <div style={{ textAlign: 'center', padding: '0.5rem 0' }}>
      <div style={{ fontSize: '1.25rem', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{time}</div>
      <div style={{ fontSize: '0.75rem', opacity: 0.6 }}>{date}</div>
    </div>
  )
}

function App() {
  const [setupComplete, setSetupComplete] = useState(null)
  const [loading, setLoading] = useState(true)
  const [streamUrl, setStreamUrl] = useState(null)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  // Close mobile menu on route change
  useEffect(() => {
    setMobileMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    fetchSetupStatus()
      .then((data) => {
        setSetupComplete(!!data.setup_complete)
      })
      .catch(() => {
        setSetupComplete(false)
      })
      .finally(() => setLoading(false))
    fetchStreamUrl()
      .then((data) => setStreamUrl(data?.url || null))
      .catch(() => {})
  }, [])

  function handleSetupComplete() {
    // Unblock routing immediately, then confirm with the server.
    setSetupComplete(true)
    fetchSetupStatus()
      .then((data) => setSetupComplete(!!data.setup_complete))
      .catch(() => {})
  }

  if (loading || setupComplete === null) {
    return (
      <div className="loading-screen">
        <div className="loading-spinner" />
        <p>Loading AI Radio DJ...</p>
      </div>
    )
  }

  if (!setupComplete) {
    return (
      <Routes>
        <Route path="/setup" element={
          <div className="setup-page">
            <Setup onComplete={handleSetupComplete} />
          </div>
        } />
        <Route path="*" element={<Navigate to="/setup" replace />} />
      </Routes>
    )
  }

  return (
    <Routes>
      <Route path="/visualizer" element={<ErrorBoundary><Visualizer /></ErrorBoundary>} />
      <Route path="/setup" element={<Navigate to="/" replace />} />
      <Route path="*" element={
        <div className="app-layout">
          <button className="mobile-menu-btn" onClick={() => setMobileMenuOpen(!mobileMenuOpen)} aria-label="Toggle menu">
            {mobileMenuOpen ? '\u2715' : '\u2630'}
          </button>
          {mobileMenuOpen && <div className="mobile-overlay" onClick={() => setMobileMenuOpen(false)} />}
          <aside className={`sidebar ${mobileMenuOpen ? 'sidebar-open' : ''}`}>
            <div className="sidebar-brand">
              <span className="brand-icon">&#9835;</span>
              <h1>AI Radio DJ</h1>
            </div>
            <nav>
              <NavLink to="/dashboard" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                <span className="nav-icon">&#9673;</span>
                Dashboard
              </NavLink>
              <NavLink to="/styles" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                <span className="nav-icon">&#9835;</span>
                Styles
              </NavLink>
              <NavLink to="/dj-config" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                <span className="nav-icon">&#9881;</span>
                DJ Config
              </NavLink>
              <NavLink to="/announcements" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                <span className="nav-icon">&#9993;</span>
                Announcements
              </NavLink>
              <NavLink to="/playlog" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                <span className="nav-icon">&#9776;</span>
                Play Log
              </NavLink>
              <div className="nav-divider" />
              <NavLink to="/shows" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                <span className="nav-icon">&#128197;</span>
                Shows
              </NavLink>
              <NavLink to="/recordings" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                <span className="nav-icon">&#128308;</span>
                Recordings
              </NavLink>
              <div className="nav-divider" />
              <NavLink to="/visualizer" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                <span className="nav-icon">&#127916;</span>
                Visualizer
              </NavLink>
              <NavLink to="/providers" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                <span className="nav-icon">&#128273;</span>
                Providers
              </NavLink>
            </nav>
            <div className="sidebar-clock">
              <SidebarClock />
            </div>
            <div className="sidebar-player">
              <AudioPlayer streamUrl={streamUrl} compact />
            </div>
          </aside>
          <main className="main-content">
            <ErrorBoundary>
            <Routes>
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/styles" element={<Styles />} />
              <Route path="/dj-config" element={<DJConfig />} />
              <Route path="/announcements" element={<Announcements />} />
              <Route path="/playlog" element={<PlayLog />} />
              <Route path="/shows" element={<Shows />} />
              <Route path="/recordings" element={<Recordings />} />
              <Route path="/providers" element={<Providers />} />
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
            </Routes>
            </ErrorBoundary>
          </main>
        </div>
      } />
    </Routes>
  )
}

export default App
