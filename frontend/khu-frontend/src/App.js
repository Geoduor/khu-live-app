import { useState, useEffect, useCallback } from "react";
import "./App.css";
import { getLeagues, getStandings, getFixtures, getResults, getLiveMatches, getHealth, refreshData } from "./api";
import { usePushNotifications } from "./hooks/usePushNotifications";
import LeagueTable from "./components/LeagueTable";
import MatchCard from "./components/MatchCard";
import LoadingState from "./components/LoadingState";
import ErrorState from "./components/ErrorState";
import TeamProfile from "./components/TeamProfile";
import MatchDetail from "./components/MatchDetail";

const TABS = [
  { id: "home", icon: "🏠", label: "Home" },
  { id: "table", icon: "📊", label: "Table" },
  { id: "fixtures", icon: "📅", label: "Fixtures" },
  { id: "results", icon: "⚽", label: "Results" },
];

const POLL_INTERVAL_MS = 45000; // 45s — matches FotMob/SofaScore live polling cadence

function App() {
  const [tab, setTab] = useState("home");
  const [leagues, setLeagues] = useState([]);
  const [selectedLeague, setSelectedLeague] = useState("premier_league_men");
  const [standings, setStandings] = useState(null);
  const [fixtures, setFixtures] = useState(null);
  const [results, setResults] = useState(null);
  const [live, setLive] = useState(null);
  const [health, setHealth] = useState(null);

  const [loadingLeagues, setLoadingLeagues] = useState(true);
  const [loadingStandings, setLoadingStandings] = useState(true);
  const [loadingFixtures, setLoadingFixtures] = useState(true);
  const [loadingResults, setLoadingResults] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [isTabVisible, setIsTabVisible] = useState(!document.hidden);

  const [backendError, setBackendError] = useState(null);

  // ── Navigation overlay: team profile / match detail ──
  // Kept as a simple stack so "Back" always returns to exactly where you were,
  // same pattern FotMob uses for drill-down navigation without full page reloads.
  const [overlay, setOverlay] = useState(null); // { type: 'team'|'match', url: string } | null
  const openTeam = (url) => setOverlay({ type: "team", url });
  const openMatch = (url) => setOverlay({ type: "match", url });
  const closeOverlay = () => setOverlay(null);

  const { supported: pushSupported, isSubscribed, loading: pushLoading, subscribe, unsubscribe } = usePushNotifications();

  const handleBellClick = async () => {
    if (isSubscribed) {
      await unsubscribe();
    } else {
      const result = await subscribe();
      if (!result.success) {
        alert(result.reason || "Could not enable notifications");
      }
    }
  };

  // ── Track browser tab visibility — pause polling when tab is hidden ──
  // (Same technique ESPN/FotMob use to avoid wasting battery/data in background tabs)
  useEffect(() => {
    const handleVisibilityChange = () => setIsTabVisible(!document.hidden);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, []);

  // ── Load leagues list on mount ──
  useEffect(() => {
    getLeagues()
      .then(data => {
        setLeagues(data.leagues || []);
        setLoadingLeagues(false);
      })
      .catch(err => {
        console.error("Failed to load leagues:", err);
        setBackendError("Cannot connect to backend server. Make sure it's running on http://localhost:8000");
        setLoadingLeagues(false);
      });
  }, []);

  // ── Load health status ──
  const checkHealth = useCallback(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth({ status: "unreachable" }));
  }, []);

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 60000); // check every 60s
    return () => clearInterval(interval);
  }, [checkHealth]);

  // ── Load standings when league selection changes ──
  useEffect(() => {
    setLoadingStandings(true);
    getStandings(selectedLeague)
      .then(data => {
        setStandings(data);
        setLoadingStandings(false);
      })
      .catch(err => {
        console.error("Failed to load standings:", err);
        setStandings({ error: "Could not load standings", standings: [] });
        setLoadingStandings(false);
      });
  }, [selectedLeague]);

  // ── Load fixtures ──
  useEffect(() => {
    getFixtures()
      .then(data => {
        setFixtures(data);
        setLoadingFixtures(false);
      })
      .catch(err => {
        console.error("Failed to load fixtures:", err);
        setFixtures({ error: "Could not load fixtures", fixtures: [] });
        setLoadingFixtures(false);
      });
  }, []);

  // ── Load results ──
  useEffect(() => {
    getResults()
      .then(data => {
        setResults(data);
        setLoadingResults(false);
      })
      .catch(err => {
        console.error("Failed to load results:", err);
        setResults({ error: "Could not load results", results: [] });
        setLoadingResults(false);
      });
  }, []);

  // ── Load live matches ──
  useEffect(() => {
    getLiveMatches().then(setLive).catch(() => setLive({ live: [] }));
  }, []);

  // ── Smart auto-polling ──
  // Refreshes standings/fixtures/results every 45s, but only while the tab is visible.
  // This mirrors how professional live-score apps (FotMob, SofaScore) behave —
  // no point burning bandwidth/battery updating a screen nobody is looking at.
  useEffect(() => {
    if (!isTabVisible) return; // don't poll while tab is hidden

    const interval = setInterval(() => {
      getStandings(selectedLeague).then(setStandings).catch(() => {});
      getFixtures().then(setFixtures).catch(() => {});
      getResults().then(setResults).catch(() => {});
      getLiveMatches().then(setLive).catch(() => {});
      checkHealth();
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [isTabVisible, selectedLeague, checkHealth]);

  // ── Immediately refresh the moment the tab becomes visible again ──
  // (e.g. user was on another app/tab and comes back — don't make them wait 45s)
  useEffect(() => {
    if (isTabVisible) {
      getStandings(selectedLeague).then(setStandings).catch(() => {});
      getFixtures().then(setFixtures).catch(() => {});
      getResults().then(setResults).catch(() => {});
      getLiveMatches().then(setLive).catch(() => {});
      checkHealth();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isTabVisible]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshData();
      const [standingsData, fixturesData, resultsData] = await Promise.all([
        getStandings(selectedLeague),
        getFixtures(),
        getResults(),
      ]);
      setStandings(standingsData);
      setFixtures(fixturesData);
      setResults(resultsData);
      checkHealth();
    } catch (err) {
      console.error("Refresh failed:", err);
    }
    setRefreshing(false);
  };

  // ── If backend is completely unreachable, show a clear error screen ──
  if (backendError) {
    return (
      <div className="App">
        <div className="flag-stripe">
          <div className="s1" /><div className="s2" /><div className="s3" /><div className="s4" />
        </div>
        <ErrorState
          title="Backend Not Running"
          message={backendError}
          detail="Run 'uvicorn main:app --reload --port 8000' in your backend folder, then refresh this page."
        />
      </div>
    );
  }

  return (
    <div className="App">
      {/* Header */}
      <div className="header">
        <div className="flag-stripe">
          <div className="s1" /><div className="s2" /><div className="s3" /><div className="s4" />
        </div>
        <div className="header-inner">
          <div className="logo">
            <div className="logo-shield">🏑</div>
            <div className="logo-text">
              <div className="logo-khu">KHU</div>
              <div className="logo-full">Kenya Hockey Union</div>
            </div>
          </div>
          <div className="header-right">
            {pushSupported && (
              <button
                className={`bell-btn ${isSubscribed ? "bell-active" : ""}`}
                onClick={handleBellClick}
                disabled={pushLoading}
                title={isSubscribed ? "Live match alerts ON" : "Get notified when matches go live"}
              >
                {isSubscribed ? "🔔" : "🔕"}
              </button>
            )}
            <button
              className={`refresh-btn ${refreshing ? "spinning" : ""}`}
              onClick={handleRefresh}
              disabled={refreshing}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="23 4 23 10 17 10" />
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
              </svg>
              {refreshing ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        </div>
        <div className="status-bar">
          <div className={`status-dot ${
            health?.circuit_breaker?.state === "OPEN" ? "error" :
            health?.status === "live" ? "live" :
            health?.status === "partial" ? "loading" :
            health?.status === "cached" ? "loading" :
            health?.status === "error" || health?.status === "unreachable" ? "error" :
            "loading"
          }`} />
          <span style={{ color: "var(--muted)" }}>
            {health?.circuit_breaker?.state === "OPEN"
              ? "KHU site unreachable — showing cached data (auto-retry paused)"
              : health?.status === "live"
              ? `Connected to KHU live feed · ${health.leagues_cached || 0} leagues loaded`
              : health?.status === "partial"
              ? "Some leagues live, others showing last cached data"
              : health?.status === "cached"
              ? "Showing cached data from last successful sync"
              : health?.status === "error"
              ? "KHU site unreachable — showing last known data"
              : health?.status === "unreachable"
              ? "Backend server unreachable"
              : "Connecting to backend..."}
          </span>
          {standings?._is_stale && (
            <span style={{
              marginLeft: "auto", fontSize: 10, fontWeight: 700, color: "var(--amber)",
              background: "rgba(240,165,0,0.12)", padding: "2px 8px", borderRadius: 10,
            }}>
              ⏱ STALE DATA
            </span>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="main">
        {overlay?.type === "team" && (
          <TeamProfile teamUrl={overlay.url} onBack={closeOverlay} onOpenTeam={openTeam} />
        )}
        {overlay?.type === "match" && (
          <MatchDetail matchUrl={overlay.url} onBack={closeOverlay} onOpenTeam={openTeam} />
        )}

        {!overlay && tab === "home" && (
          <HomeView
            leagues={leagues}
            loadingLeagues={loadingLeagues}
            onSelectLeague={(key) => { setSelectedLeague(key); setTab("table"); }}
            fixtures={fixtures}
            results={results}
            live={live}
            loadingFixtures={loadingFixtures}
            loadingResults={loadingResults}
            onOpenMatch={openMatch}
            onOpenTeam={openTeam}
          />
        )}

        {!overlay && tab === "table" && (
          <TableView
            leagues={leagues}
            selectedLeague={selectedLeague}
            setSelectedLeague={setSelectedLeague}
            standings={standings}
            loading={loadingStandings}
            onOpenTeam={openTeam}
          />
        )}

        {!overlay && tab === "fixtures" && (
          <FixturesView fixtures={fixtures} loading={loadingFixtures} onOpenMatch={openMatch} onOpenTeam={openTeam} />
        )}

        {!overlay && tab === "results" && (
          <ResultsView results={results} loading={loadingResults} onOpenMatch={openMatch} onOpenTeam={openTeam} />
        )}
      </div>

      {/* Bottom Nav */}
      <div className="bnav">
        {TABS.map(t => (
          <button key={t.id} className={`bnav-btn ${tab === t.id && !overlay ? "active" : ""}`} onClick={() => { setTab(t.id); closeOverlay(); }}>
            <span className="bnav-icon">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════
// HOME VIEW
// ══════════════════════════════════════════════════
function HomeView({ leagues, loadingLeagues, onSelectLeague, fixtures, results, live, loadingFixtures, loadingResults, onOpenMatch, onOpenTeam }) {
  const liveMatches = live?.live || [];

  return (
    <>
      <div className="section" style={{ paddingBottom: 0 }}>
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 2, color: "var(--red)", textTransform: "uppercase", marginBottom: 6 }}>
            🇰🇪 Official Live App
          </div>
          <div style={{ fontFamily: "'Barlow Condensed',sans-serif", fontWeight: 900, fontSize: 30, lineHeight: 1.05 }}>
            Kenya Hockey Union
          </div>
          <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
            Live tables · fixtures · results — direct from kenyahockeyunion.org
          </div>
        </div>
      </div>

      {liveMatches.length > 0 && (
        <div className="section">
          <div className="sec-head">
            <span className="sec-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="match-state-live"><span className="pulse-dot" /> LIVE NOW</span>
            </span>
            <span className="sec-badge">{liveMatches.length}</span>
          </div>
          <div className="match-list">
            {liveMatches.map((m, i) => <MatchCard key={i} match={m} onOpenMatch={onOpenMatch} onOpenTeam={onOpenTeam} />)}
          </div>
        </div>
      )}

      <div className="section">
        <div className="sec-head">
          <span className="sec-title">All Leagues</span>
        </div>
        {loadingLeagues ? (
          <LoadingState message="Loading leagues..." />
        ) : leagues.length === 0 ? (
          <ErrorState title="No leagues found" message="Backend returned no leagues." compact />
        ) : (
          <div className="league-grid">
            {leagues.map(l => (
              <div key={l.key} className="league-card" onClick={() => onSelectLeague(l.key)}>
                <div className="league-card-tier">{l.short}</div>
                <div className="league-card-name">{l.name}</div>
                <div className="league-card-teams">View standings →</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="section">
        <div className="sec-head">
          <span className="sec-title">Recent Results</span>
        </div>
        {loadingResults ? (
          <LoadingState message="Loading results..." />
        ) : results?.error ? (
          <ErrorState title="Could not load results" message={results.error} compact />
        ) : results?.results?.length > 0 ? (
          <div className="match-list">
            {results.results.slice(0, 3).map((m, i) => <MatchCard key={i} match={m} onOpenMatch={onOpenMatch} onOpenTeam={onOpenTeam} />)}
          </div>
        ) : (
          <ErrorState
            title="No results parsed yet"
            message="The homepage scraper could not identify match result blocks. This needs scraper refinement."
            compact
          />
        )}
      </div>

      <div className="section">
        <div className="sec-head">
          <span className="sec-title">Upcoming Fixtures</span>
        </div>
        {loadingFixtures ? (
          <LoadingState message="Loading fixtures..." />
        ) : fixtures?.error ? (
          <ErrorState title="Could not load fixtures" message={fixtures.error} compact />
        ) : fixtures?.fixtures?.length > 0 ? (
          <div className="match-list">
            {fixtures.fixtures.slice(0, 3).map((m, i) => <MatchCard key={i} match={m} onOpenMatch={onOpenMatch} onOpenTeam={onOpenTeam} />)}
          </div>
        ) : (
          <ErrorState
            title="No fixtures parsed yet"
            message="The homepage scraper could not identify fixture blocks. This needs scraper refinement."
            compact
          />
        )}
      </div>
    </>
  );
}

// ══════════════════════════════════════════════════
// TABLE VIEW
// ══════════════════════════════════════════════════
function TableView({ leagues, selectedLeague, setSelectedLeague, standings, loading, onOpenTeam }) {
  return (
    <div className="section">
      <div className="sec-head"><span className="sec-title">League Table</span></div>

      <div className="pills">
        {leagues.map(l => (
          <button
            key={l.key}
            className={`pill ${selectedLeague === l.key ? "active" : ""}`}
            onClick={() => setSelectedLeague(l.key)}
          >
            {l.short}
          </button>
        ))}
      </div>

      {loading ? (
        <LoadingState message="Fetching live standings from KHU..." />
      ) : standings?.error ? (
        <ErrorState title="Could not load standings" message={standings.error} />
      ) : standings?.standings?.length > 0 ? (
        <>
          <div style={{ marginBottom: 10, fontSize: 12, color: "var(--muted)" }}>
            {standings.league} — {standings.total_teams} teams
          </div>
          <LeagueTable data={standings.standings} onOpenTeam={onOpenTeam} />
          <div style={{ marginTop: 10, fontSize: 10, color: "var(--muted)" }}>
            Source: kenyahockeyunion.org · Last scraped: {standings.scraped_at ? new Date(standings.scraped_at).toLocaleString() : "unknown"}
          </div>
        </>
      ) : (
        <ErrorState title="No standings data" message="This league returned no teams. Check the backend logs." />
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════
// FIXTURES VIEW
// ══════════════════════════════════════════════════
function FixturesView({ fixtures, loading, onOpenMatch, onOpenTeam }) {
  return (
    <div className="section">
      <div className="sec-head"><span className="sec-title">Upcoming Fixtures</span></div>
      {loading ? (
        <LoadingState message="Loading fixtures..." />
      ) : fixtures?.error ? (
        <ErrorState title="Could not load fixtures" message={fixtures.error} />
      ) : fixtures?.fixtures?.length > 0 ? (
        <div className="match-list">
          {fixtures.fixtures.map((m, i) => <MatchCard key={i} match={m} onOpenMatch={onOpenMatch} onOpenTeam={onOpenTeam} />)}
        </div>
      ) : (
        <ErrorState
          title="No fixtures found"
          message="The KHU homepage scraper didn't identify structured fixture data. See README about refining the homepage scraper selectors."
        />
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════
// RESULTS VIEW
// ══════════════════════════════════════════════════
function ResultsView({ results, loading, onOpenMatch, onOpenTeam }) {
  return (
    <div className="section">
      <div className="sec-head"><span className="sec-title">Results</span></div>
      {loading ? (
        <LoadingState message="Loading results..." />
      ) : results?.error ? (
        <ErrorState title="Could not load results" message={results.error} />
      ) : results?.results?.length > 0 ? (
        <div className="match-list">
          {results.results.map((m, i) => <MatchCard key={i} match={m} onOpenMatch={onOpenMatch} onOpenTeam={onOpenTeam} />)}
        </div>
      ) : (
        <ErrorState
          title="No results found"
          message="The KHU homepage scraper didn't identify structured result data. See README about refining the homepage scraper selectors."
        />
      )}
    </div>
  );
}

export default App;
