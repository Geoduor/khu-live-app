import React from 'react';
import { ClaudeChat } from '../components/ClaudeChat';

export const HockeyInsights = () => {
  return (
    <div className="hockey-insights">
      <h1>Hockey AI Insights</h1>
      <p>Ask Claude about players, teams, strategies, and match analysis</p>
      <ClaudeChat context="hockey" />
    </div>
  );
};