import type { ReactNode } from "react";
import type { ApplicationRecord } from "./types";

export type ViewName =
  | "landing"
  | "home"
  | "onboarding"
  | "new-app"
  | "application"
  | "study"
  | "growth"
  | "settings";

export interface View {
  name: ViewName;
  appId?: string;
}

const STATUS_GROUPS: { label: string; statuses: string[] }[] = [
  { label: "In review", statuses: ["analyzing", "pending_review", "approved"] },
  { label: "Finalized", statuses: ["finalized"] },
  { label: "Archived", statuses: ["archived"] },
];

export default function Shell({
  view,
  applications,
  crumb,
  canGoBack,
  onNavigate,
  onBack,
  onHome,
  children,
}: {
  view: View;
  applications: ApplicationRecord[];
  crumb: string;
  canGoBack: boolean;
  onNavigate: (v: View) => void;
  onBack: () => void;
  onHome: () => void;
  children: ReactNode;
}) {
  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main navigation">
        <div className="brand">resume-agent</div>

        <button
          className={`nav-item ${view.name === "home" ? "active" : ""}`}
          onClick={onHome}
        >
          ⌂ Home
        </button>
        <button
          className={`nav-item ${view.name === "new-app" ? "active" : ""}`}
          onClick={() => onNavigate({ name: "new-app" })}
        >
          ＋ New application
        </button>
        <button
          className={`nav-item ${view.name === "onboarding" ? "active" : ""}`}
          onClick={() => onNavigate({ name: "onboarding" })}
        >
          ☰ Base resume
        </button>
        <button
          className={`nav-item ${view.name === "study" ? "active" : ""}`}
          onClick={() => onNavigate({ name: "study" })}
        >
          ▤ Study Guide
        </button>
        <button
          className={`nav-item ${view.name === "growth" ? "active" : ""}`}
          onClick={() => onNavigate({ name: "growth" })}
        >
          ↗ Career Growth
        </button>
        <button
          className={`nav-item ${view.name === "settings" ? "active" : ""}`}
          onClick={() => onNavigate({ name: "settings" })}
        >
          ⚙ Settings
        </button>

        {STATUS_GROUPS.map((group) => {
          const apps = applications.filter((a) => group.statuses.includes(a.status));
          return (
            <div key={group.label}>
              <div className="nav-group">{group.label}</div>
              {apps.length === 0 && <div className="nav-empty">none</div>}
              {apps.map((app) => (
                <button
                  key={app.id}
                  className={`nav-item ${
                    view.name === "application" && view.appId === app.id ? "active" : ""
                  }`}
                  onClick={() => onNavigate({ name: "application", appId: app.id })}
                  title={`${app.company} — ${app.role_title} (${app.status})`}
                >
                  {app.company || "?"} · {app.role_title || "?"}
                </button>
              ))}
            </div>
          );
        })}
      </nav>

      <div className="main">
        <header className="topbar">
          <button onClick={onBack} disabled={!canGoBack} aria-label="Back">
            ← Back
          </button>
          <button onClick={onHome} aria-label="Home">
            ⌂ Home
          </button>
          <span className="crumb">{crumb}</span>
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
