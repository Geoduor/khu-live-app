/**
 * api.js — Connects React frontend to the KHU FastAPI backend
 *
 * Locally: falls back to http://localhost:8000 automatically.
 * In production (Vercel): set REACT_APP_API_URL to your deployed
 * Render backend URL, e.g. https://khu-backend.onrender.com
 */
import axios from "axios";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE,
  timeout: 15000,
});

// ── Leagues ──
export const getLeagues = () => api.get("/api/leagues").then(r => r.data);

// ── Standings ──
export const getStandings = (leagueKey) =>
  api.get(`/api/standings/${leagueKey}`).then(r => r.data);

export const getAllStandings = () =>
  api.get("/api/standings/all").then(r => r.data);

// ── Fixtures & Results ──
export const getFixtures = () => api.get("/api/fixtures").then(r => r.data);
export const getResults = () => api.get("/api/results").then(r => r.data);
export const getLiveMatches = () => api.get("/api/live").then(r => r.data);
export const getPlayoffBracket = () => api.get("/api/playoffs/nlm").then(r => r.data);
export const getTeamProfile = (url, name = "") => api.get("/api/team", { params: { url, name } }).then(r => r.data);
export const getMatchDetail = (url) => api.get("/api/match", { params: { url } }).then(r => r.data);
export const getAllTeamsFlat = () => api.get("/api/teams/all").then(r => r.data);
export const updatePushFavorites = (endpoint, favoriteTeams) =>
  api.post("/api/push/update-favorites", { endpoint, favoriteTeams }).then(r => r.data);

// ── Health check ──
export const getHealth = () => api.get("/api/health").then(r => r.data);

// ── Manual refresh trigger ──
export const refreshData = () => api.post("/api/refresh").then(r => r.data);

export default api;
