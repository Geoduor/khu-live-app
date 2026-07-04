/**
 * api.js — Connects React frontend to the KHU FastAPI backend
 * Backend must be running on http://localhost:8000
 */
import axios from "axios";

const API_BASE = "http://localhost:8000";

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
export const getTeamProfile = (url) => api.get("/api/team", { params: { url } }).then(r => r.data);
export const getMatchDetail = (url) => api.get("/api/match", { params: { url } }).then(r => r.data);

// ── Health check ──
export const getHealth = () => api.get("/api/health").then(r => r.data);

// ── Manual refresh trigger ──
export const refreshData = () => api.post("/api/refresh").then(r => r.data);

export default api;
