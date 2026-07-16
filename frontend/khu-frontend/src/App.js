import { useState, useEffect, useCallback, useRef } from "react";
import "./App.css";
import { getLeagues, getStandings, getFixtures, getResults, getLiveMatches, getHealth, refreshData } from "./api";
import { usePushNotifications } from "./hooks/usePushNotifications";
import { useFavorites, useOnboarding } from "./hooks/useFavorites";
import { useTheme } from "./hooks/useTheme";
import LeagueTable from "./components/LeagueTable";
import MatchCard from "./components/MatchCard";
import LoadingState from "./components/LoadingState";
import ErrorState from "./components/ErrorState";
import TeamProfile from "./components/TeamProfile";
import MatchDetail from "./components/MatchDetail";
import OnboardingPicker from "./components/OnboardingPicker";

const TABS = [
  { id: "home", icon: "🏠", label: "Home" },
  { id: "table", icon: "📊", label: "Table" },
  { id: "fixtures", icon: "📅", label: "Fixtures" },
  { id: "results", icon: "🏑", label: "Results" },
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
  const openTeam = (url, name = "") => setOverlay({ type: "team", url, name });
  const openMatch = (url) => setOverlay({ type: "match", url });
  const closeOverlay = () => setOverlay(null);

  const { supported: pushSupported, isSubscribed, loading: pushLoading, subscribe, unsubscribe } = usePushNotifications();
  const { favorites, favoriteList, isFavorite, toggleFavorite } = useFavorites();
  const { toggleTheme, isDark } = useTheme();
  const { hasSeenOnboarding, markOnboardingSeen } = useOnboarding();

  const handleBellClick = async () => {
    if (isSubscribed) {
      await unsubscribe();
    } else {
      const result = await subscribe(Object.keys(favorites));
      if (!result.success) {
        alert(result.reason || "Could not enable notifications");
      }
    }
  };

  // ── First-run onboarding: "which teams do you follow?" ──
  // Only shown once ever per device (tracked via localStorage), and only
  // once leagues have actually loaded so the picker has real teams to show.
  const showOnboarding = !hasSeenOnboarding && !loadingLeagues && leagues.length > 0;

  const handleOnboardingComplete = (chosenTeams) => {
    // chosenTeams is [{team_url, team_name}, ...] from OnboardingPicker,
    // or [] if the user tapped "Skip for now".
    chosenTeams.forEach(({ team_url, team_name }) => toggleFavorite(team_url, team_name));
    markOnboardingSeen();
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
  //
  // IMPORTANT: this interval must NOT reset every time selectedLeague changes,
  // otherwise switching leagues repeatedly restarts the 45s clock and causes
  // bursts of requests that look like much faster polling than intended.
  // We read the current league via a ref instead of a dependency, so the
  // interval itself is created exactly once and keeps its own steady cadence.
  const selectedLeagueRef = useRef(selectedLeague);
  useEffect(() => { selectedLeagueRef.current = selectedLeague; }, [selectedLeague]);

  useEffect(() => {
    if (!isTabVisible) return; // don't poll while tab is hidden

    const interval = setInterval(() => {
      getStandings(selectedLeagueRef.current).then(setStandings).catch(() => {});
      getFixtures().then(setFixtures).catch(() => {});
      getResults().then(setResults).catch(() => {});
      getLiveMatches().then(setLive).catch(() => {});
      checkHealth();
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [isTabVisible, checkHealth]);

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
      {showOnboarding && <OnboardingPicker onComplete={handleOnboardingComplete} />}

      {/* Header */}
      <div className="header">
        <div className="flag-stripe">
          <div className="s1" /><div className="s2" /><div className="s3" /><div className="s4" />
        </div>
        <div className="header-inner">
          <div className="logo">
            <img src="/khu-logo.png" alt="KHU Logo" className="logo-shield-img" />
            <div className="logo-text">
              <div className="logo-khu">KHU</div>
              <div className="logo-full">Kenya Hockey Union</div>
            </div>
          </div>
          <div className="header-right">
            <button
              className="theme-toggle-btn"
              onClick={toggleTheme}
              title={isDark ? "Switch to light mode" : "Switch to dark mode"}
            >
              {isDark ? "☀️" : "🌙"}
            </button>
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
          <TeamProfile teamUrl={overlay.url} teamName={overlay.name} onBack={closeOverlay} onOpenTeam={openTeam} isFavorite={isFavorite} toggleFavorite={toggleFavorite} />
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
            favoriteList={favoriteList}
            isFavorite={isFavorite}
            toggleFavorite={toggleFavorite}
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
            isFavorite={isFavorite}
            toggleFavorite={toggleFavorite}
          />
        )}

        {!overlay && tab === "fixtures" && (
          <FixturesView fixtures={fixtures} loading={loadingFixtures} onOpenMatch={openMatch} onOpenTeam={openTeam} isFavorite={isFavorite} toggleFavorite={toggleFavorite} />
        )}

        {!overlay && tab === "results" && (
          <ResultsView results={results} loading={loadingResults} onOpenMatch={openMatch} onOpenTeam={openTeam} isFavorite={isFavorite} toggleFavorite={toggleFavorite} />
        )}
      </div>

      {/* Bottom Nav */}
      <div className="bnav">
        {TABS.map(t => (
          <button key={t.id} className={`bnav-btn ${tab === t.id && !overlay ? "active" : ""}`} onClick={() => { setTab(t.id); closeOverlay(); }}>
            <span className="bnav-icon-wrap"><span className="bnav-icon">{t.icon}</span></span>
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
function HomeView({ leagues, loadingLeagues, onSelectLeague, fixtures, results, live, loadingFixtures, loadingResults, onOpenMatch, onOpenTeam, favoriteList, isFavorite, toggleFavorite }) {
  const liveMatches = live?.live || [];
  const nextFixture = fixtures?.fixtures?.[0];
  const mostRecentResult = (results?.most_recent || results?.results || [])[0];

  // The scoreboard hero shows, in priority order: a live match right
  // now, otherwise the soonest upcoming fixture, otherwise the most
  // recent result — always something concrete and current, never a
  // generic tagline with nothing real behind it.
  const heroMatch = liveMatches[0] || nextFixture || mostRecentResult;
  const heroState = liveMatches[0] ? "LIVE" : nextFixture ? "NS" : "FT";

  // League tiers, visually distinguished by actual importance in
  // Kenyan hockey's real league structure — Premier League is the
  // top flight, Super League the second tier, National League zones
  // are regional/grassroots — rather than one flat identical grid.
  const premierLeagues = leagues.filter(l => l.short.startsWith("PL"));
  const superLeagues = leagues.filter(l => l.short.startsWith("SL"));
  const nationalLeagues = leagues.filter(l => l.short.startsWith("NLM"));

  return (
    <>
      {/* ── SCOREBOARD HERO ── */}
      <div className="section" style={{ paddingBottom: 8 }}>
        <div className="scoreboard-hero">
          <div className="scoreboard-hero-top">
            <span className="scoreboard-hero-brand">KHU LIVE</span>
            {heroState === "LIVE" && (
              <span className="match-state-live"><span className="pulse-dot" /> LIVE</span>
            )}
            {heroState === "NS" && <span className="scoreboard-hero-tag">NEXT UP</span>}
            {heroState === "FT" && <span className="scoreboard-hero-tag">LATEST RESULT</span>}
          </div>

          {heroMatch ? (
            <div className="scoreboard-hero-body" onClick={() => heroMatch.match_url && onOpenMatch(heroMatch.match_url)}>
              <div className="scoreboard-hero-team">
                {heroMatch.home_logo_url && <img src={heroMatch.home_logo_url} alt="" className="scoreboard-hero-logo" />}
                <span>{heroMatch.home_team}</span>
              </div>
              <div className="scoreboard-hero-center">
                {heroState === "NS" ? (
                  <>
                    <div className="scoreboard-hero-vs">VS</div>
                    <div className="scoreboard-hero-time">{heroMatch.time || heroMatch.date}</div>
                  </>
                ) : (
                  <div className="scoreboard-hero-score">
                    {heroMatch.home_score ?? 0}<span className="scoreboard-hero-dash">–</span>{heroMatch.away_score ?? 0}
                  </div>
                )}
              </div>
              <div className="scoreboard-hero-team">
                {heroMatch.away_logo_url && <img src={heroMatch.away_logo_url} alt="" className="scoreboard-hero-logo" />}
                <span>{heroMatch.away_team}</span>
              </div>
            </div>
          ) : (
            <div className="scoreboard-hero-empty">Live tables, fixtures &amp; results — direct from kenyahockeyunion.org</div>
          )}

          {heroMatch?.league && <div className="scoreboard-hero-league">{heroMatch.league}</div>}
        </div>
      </div>

      {favoriteList && favoriteList.length > 0 && (
        <div className="section" style={{ paddingBottom: 8 }}>
          <div className="sec-head">
            <span className="sec-title">⭐ Your Teams</span>
          </div>
          <div className="your-teams-strip">
            {favoriteList.map((f) => (
              <button
                key={f.team_url}
                className="your-team-chip"
                onClick={() => onOpenTeam(f.team_url, f.team_name)}
              >
                {f.team_name}
              </button>
            ))}
          </div>
        </div>
      )}

      {liveMatches.length > 1 && (
        <div className="section">
          <div className="sec-head">
            <span className="sec-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="match-state-live"><span className="pulse-dot" /> LIVE NOW</span>
            </span>
            <span className="sec-badge">{liveMatches.length}</span>
          </div>
          <div className="match-list">
            {liveMatches.slice(1).map((m, i) => <MatchCard key={i} match={m} onOpenMatch={onOpenMatch} onOpenTeam={onOpenTeam} isFavorite={isFavorite} toggleFavorite={toggleFavorite} />)}
          </div>
        </div>
      )}

      {/* ── LEAGUE HIERARCHY — tiered by actual importance ── */}
      <div className="section">
        <div className="sec-head">
          <span className="sec-title">All Leagues</span>
        </div>
        {loadingLeagues ? (
          <LoadingState message="Loading leagues..." />
        ) : leagues.length === 0 ? (
          <ErrorState title="No leagues found" message="Backend returned no leagues." compact />
        ) : (
          <>
            {premierLeagues.length > 0 && (
              <div className="league-tier league-tier-premier">
                <div className="league-tier-label">🏆 Premier League — Top Flight</div>
                <div className="league-grid">
                  {premierLeagues.map(l => (
                    <div key={l.key} className="league-card league-card-premier" onClick={() => onSelectLeague(l.key)}>
                      <div className="league-card-tier">{l.short}</div>
                      <div className="league-card-name">{l.name}</div>
                      <div className="league-card-teams">View standings →</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {superLeagues.length > 0 && (
              <div className="league-tier">
                <div className="league-tier-label">Super League — Second Tier</div>
                <div className="league-grid">
                  {superLeagues.map(l => (
                    <div key={l.key} className="league-card" onClick={() => onSelectLeague(l.key)}>
                      <div className="league-card-tier">{l.short}</div>
                      <div className="league-card-name">{l.name}</div>
                      <div className="league-card-teams">View standings →</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {nationalLeagues.length > 0 && (
              <div className="league-tier">
                <div className="league-tier-label">National League — Regional Zones</div>
                <div className="league-grid league-grid-compact">
                  {nationalLeagues.map(l => (
                    <div key={l.key} className="league-card league-card-compact" onClick={() => onSelectLeague(l.key)}>
                      <div className="league-card-tier">{l.short}</div>
                      <div className="league-card-name">{l.name.replace("National League Men — ", "")}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
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
            {(results.most_recent || results.results).slice(0, 3).map((m, i) => <MatchCard key={i} match={m} onOpenMatch={onOpenMatch} onOpenTeam={onOpenTeam} isFavorite={isFavorite} toggleFavorite={toggleFavorite} />)}
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
            {fixtures.fixtures.slice(0, 3).map((m, i) => <MatchCard key={i} match={m} onOpenMatch={onOpenMatch} onOpenTeam={onOpenTeam} isFavorite={isFavorite} toggleFavorite={toggleFavorite} />)}
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
function TableView({ leagues, selectedLeague, setSelectedLeague, standings, loading, onOpenTeam, isFavorite, toggleFavorite }) {
  return (
    <div className="section">
      <div className="sec-head"><span className="sec-title">League Table</span></div>

      <div className="league-pill-row">
        {leagues.map(l => (
          <button
            key={l.key}
            className={`league-pill ${selectedLeague === l.key ? "active" : ""}`}
            onClick={() => setSelectedLeague(l.key)}
          >
            <span className="league-pill-icon">{l.short.replace("NLM-", "").slice(0, 3)}</span>
            <span className="league-pill-label">{l.short}</span>
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
          <LeagueTable data={standings.standings} onOpenTeam={onOpenTeam} isFavorite={isFavorite} toggleFavorite={toggleFavorite} />
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
function GroupedMatchList({ matches, onOpenMatch, onOpenTeam, isFavorite, toggleFavorite }) {
  // Matches arrive pre-sorted by league from the backend (see
  // LEAGUE_DISPLAY_ORDER in scraper.py) — we just need to insert a
  // header whenever the league changes as we walk down the list.
  let lastLeague = null;

  return (
    <div className="match-list">
      {matches.map((m, i) => {
        const showHeader = m.league !== lastLeague;
        lastLeague = m.league;
        return (
          <div key={i}>
            {showHeader && (
              <div className="league-group-header">{m.league}</div>
            )}
            <MatchCard
              match={m}
              onOpenMatch={onOpenMatch}
              onOpenTeam={onOpenTeam}
              isFavorite={isFavorite}
              toggleFavorite={toggleFavorite}
            />
          </div>
        );
      })}
    </div>
  );
}

function FixturesView({ fixtures, loading, onOpenMatch, onOpenTeam, isFavorite, toggleFavorite }) {
  return (
    <div className="section">
      <div className="sec-head"><span className="sec-title">Upcoming Fixtures</span></div>
      {loading ? (
        <LoadingState message="Loading fixtures..." />
      ) : fixtures?.error ? (
        <ErrorState title="Could not load fixtures" message={fixtures.error} />
      ) : fixtures?.fixtures?.length > 0 ? (
        <GroupedMatchList
          matches={fixtures.fixtures}
          onOpenMatch={onOpenMatch}
          onOpenTeam={onOpenTeam}
          isFavorite={isFavorite}
          toggleFavorite={toggleFavorite}
        />
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
function ResultsView({ results, loading, onOpenMatch, onOpenTeam, isFavorite, toggleFavorite }) {
  return (
    <div className="section">
      <div className="sec-head"><span className="sec-title">Results</span></div>
      {loading ? (
        <LoadingState message="Loading results..." />
      ) : results?.error ? (
        <ErrorState title="Could not load results" message={results.error} />
      ) : results?.results?.length > 0 ? (
        <GroupedMatchList
          matches={results.results}
          onOpenMatch={onOpenMatch}
          onOpenTeam={onOpenTeam}
          isFavorite={isFavorite}
          toggleFavorite={toggleFavorite}
        />
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
