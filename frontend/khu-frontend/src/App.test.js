jest.mock('./api', () => {
  const ok = (data) => () => Promise.resolve(data);
  return {
    __esModule: true,
    default: {
      get: ok({ data: {} }),
      post: ok({ data: {} }),
    },
    getLeagues: ok({ leagues: [] }),
    getStandings: ok({ standings: [] }),
    getFixtures: ok({ fixtures: [] }),
    getResults: ok({ results: [] }),
    getLiveMatches: ok({ live: [] }),
    getHealth: ok({ status: 'ok' }),
    getPlayoffBracket: ok({}),
    getTeamProfile: ok({}),
    getMatchDetail: ok({}),
    getAllTeamsFlat: ok({ teams: [] }),
    updatePushFavorites: ok({}),
    refreshData: ok({}),
    teamLogoUrl: (url) => url,
  };
});

jest.mock('./hooks/usePushNotifications', () => ({
  usePushNotifications: () => ({
    permission: 'default',
    isSubscribed: false,
    loading: false,
    supported: false,
    subscribe: () => {},
    unsubscribe: () => {},
  }),
}));

const { render, screen, waitFor } = require('@testing-library/react');
const App = require('./App').default;

test('renders KHU app branding', async () => {
  render(<App />);
  await waitFor(() => {
    expect(screen.getByText(/Kenya Hockey Union/i)).toBeInTheDocument();
  });
});
