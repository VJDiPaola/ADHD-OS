import { useState, useEffect } from 'react'

const API_BASE = 'http://localhost:8000/api';

function App() {
  const [stats, setStats] = useState(null);
  const [history, setHistory] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statsRes, historyRes, sessionsRes] = await Promise.all([
          fetch(`${API_BASE}/stats`),
          fetch(`${API_BASE}/history`),
          fetch(`${API_BASE}/sessions`)
        ]);

        setStats(await statsRes.json());
        setHistory(await historyRes.json());
        setSessions(await sessionsRes.json());
      } catch (error) {
        console.error("Failed to fetch dashboard data:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    // Poll every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return <div className="glass-card" style={{ textAlign: 'center' }}>Loading Neural Interface...</div>;
  }

  return (
    <div className="dashboard">
      <header>
        <h1>ADHD-OS <span style={{ fontSize: '1rem', opacity: 0.5 }}>v2.1</span></h1>
      </header>

      <div className="grid">
        {/* Energy Gauge */}
        <div className="glass-card">
          <h3>Current Capacity</h3>
          <div className="gauge-container">
            <div className="gauge-value">{stats?.current_energy || 0}<span style={{ fontSize: '1.5rem' }}>/10</span></div>
          </div>
          <div className="gauge-label">
            Multiplier: {stats?.current_multiplier}x
          </div>
        </div>

        {/* Today's Progress */}
        <div className="glass-card">
          <h3>Today's Focus</h3>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem' }}>
            <span style={{ fontSize: '3rem', fontWeight: 800, color: 'var(--accent-secondary)' }}>
              {stats?.tasks_completed_today || 0}
            </span>
            <span style={{ color: 'var(--text-secondary)' }}>tasks completed</span>
          </div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: '2fr 1fr' }}>
        {/* Task Timeline */}
        <div className="glass-card">
          <h3>Task History</h3>
          <div className="timeline">
            {history.length === 0 ? (
              <div style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>No tasks recorded yet.</div>
            ) : (
              history.map((item) => (
                <div key={item.id} className="timeline-item">
                  <div className="timeline-time">
                    {new Date(item.completed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                  <div className="timeline-content">
                    <strong>{item.task_type}</strong>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      Duration: {item.duration_minutes.toFixed(1)}m
                    </div>
                  </div>
                  <div className="status-badge">DONE</div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Recent Sessions */}
        <div className="glass-card">
          <h3>Recent Sessions</h3>
          <div className="session-list">
            {sessions.map((session) => (
              <div key={session.id} className="session-item">
                <div style={{ fontWeight: 600 }}>Session {session.id.slice(0, 8)}</div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  Last active: {session.last_active ? new Date(session.last_active.replace(' ', 'T')).toLocaleDateString() : 'Unknown'}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default App
