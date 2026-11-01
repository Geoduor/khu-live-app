import React, { useState, useEffect } from "react";
import TournamentsView from "./TournamentsView";
import SeasonsView from "./SeasonsView";
import { trackView } from "../utils/track";

/** The Cups tab: tournaments, plus the permanent record of past seasons. */
export default function CupsTab() {
  const [mode, setMode] = useState("cups");
  useEffect(() => { trackView(mode === "seasons" ? "seasons" : "cups"); }, [mode]);
  return (
    <div>
      <div className="seg" role="tablist" style={{ paddingTop: 4 }}>
        <button className={mode === "cups" ? "active" : ""} onClick={() => setMode("cups")}>Tournaments</button>
        <button className={mode === "seasons" ? "active" : ""} onClick={() => setMode("seasons")}>Past seasons</button>
      </div>
      {mode === "cups" ? <TournamentsView /> : <div className="section"><div className="sec-head"><span className="sec-title">Past seasons</span></div><SeasonsView /></div>}
    </div>
  );
}
