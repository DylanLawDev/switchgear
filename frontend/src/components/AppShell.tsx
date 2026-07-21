import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import Wordmark from "./Wordmark";
import WireStatus from "./WireStatus";
import Toaster from "./Toaster";
import LiveSync from "./LiveSync";
import { toggleTheme } from "../theme";
import styles from "./AppShell.module.css";

export const NAV_TABS = [
  { label: "Chat", code: "CH", to: "/" },
  { label: "Skills", code: "SK", to: "/skills" },
  { label: "Workflows", code: "WF", to: "/workflows" },
  { label: "Scheduler", code: "SC", to: "/scheduler" },
  { label: "Agents", code: "AG", to: "/agents" },
  { label: "Inbox", code: "IN", to: "/inbox" },
  { label: "Channels", code: "CN", to: "/channels" },
  { label: "Resources", code: "RS", to: "/resources" },
  { label: "Memories", code: "ME", to: "/memories" },
] as const;

const RAIL_KEY = "switchgear-rail";
type RailPref = "pinned" | "auto";

function getRailPref(): RailPref {
  try {
    return localStorage.getItem(RAIL_KEY) === "auto" ? "auto" : "pinned";
  } catch {
    return "pinned"; // private mode
  }
}

function setRailPref(pref: RailPref): void {
  try {
    localStorage.setItem(RAIL_KEY, pref);
  } catch {
    /* private mode */
  }
}

export default function AppShell() {
  const [autoCollapse, setAutoCollapse] = useState(() => getRailPref() === "auto");

  function toggleAutoCollapse() {
    setAutoCollapse((prev) => {
      const next = !prev;
      setRailPref(next ? "auto" : "pinned");
      return next;
    });
  }

  return (
    <div className={styles.shell}>
      <LiveSync />
      <aside className={!autoCollapse ? `${styles.rail} ${styles.railPinned}` : styles.rail}>
        <Wordmark />
        <nav className={styles.nav}>
          {NAV_TABS.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.to === "/"}
              className={({ isActive }) => (isActive ? `${styles.item} ${styles.itemActive}` : styles.item)}
            >
              <span className={styles.prefix} aria-hidden="true">
                <span className={styles.code}>{tab.code}</span>
                <span className={styles.separator}>|</span>
              </span>
              <span className={styles.label}>{tab.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className={styles.railFoot}>
          <WireStatus />
          <div className={styles.railControls}>
            <button
              type="button"
              className={`${styles.railBtn} ${styles.collapseBtn}`}
              aria-label={autoCollapse ? "keep sidebar open" : "auto-collapse sidebar"}
              aria-pressed={autoCollapse}
              onClick={(event) => {
                toggleAutoCollapse();
                event.currentTarget.blur();
              }}
            >
              {autoCollapse ? "»" : "«"}
            </button>
            <button type="button" className={styles.railBtn} aria-label="toggle theme" onClick={toggleTheme}>
              ◐
            </button>
            <NavLink
              to="/settings"
              className={({ isActive }) => isActive ? `${styles.railBtn} ${styles.railBtnActive}` : styles.railBtn}
              aria-label="settings"
            >
              ⚙
            </NavLink>
          </div>
        </div>
      </aside>
      <main className={styles.main}>
        <Outlet />
      </main>
      <Toaster />
    </div>
  );
}
