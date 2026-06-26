import { Suspense, lazy, useState } from "react";
import { Redirect, Route, Switch } from "wouter";

import { EngineProvider } from "./contexts/EngineContext";
import { StatusProvider } from "./contexts/StatusContext";
import { LoadingFallback } from "./components/LoadingFallback";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";

// Code-split each page — initial bundle only ships the shell + first page.
const TradePage = lazy(() => import("./pages/TradePage").then((m) => ({ default: m.TradePage })));
const MarketsPage = lazy(() => import("./pages/MarketsPage").then((m) => ({ default: m.MarketsPage })));
const StrategiesPage = lazy(() => import("./pages/StrategiesPage").then((m) => ({ default: m.StrategiesPage })));
const RiskPage = lazy(() => import("./pages/RiskPage").then((m) => ({ default: m.RiskPage })));
const AuditPage = lazy(() => import("./pages/AuditPage").then((m) => ({ default: m.AuditPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <StatusProvider>
      <EngineProvider>
        <div className="app-shell app-shell--with-sidebar">
          <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

          <div className="app-main">
            <button
              className="hamburger"
              onClick={() => setSidebarOpen(true)}
              aria-label="打开导航"
            >
              ☰
            </button>
            <Topbar />
            <Suspense fallback={<LoadingFallback title="加载中" hint="请稍候" />}>
              <Switch>
                <Route path="/" component={() => <Redirect to="/trade" />} />
                <Route path="/trade" component={TradePage} />
                <Route path="/markets" component={MarketsPage} />
                <Route path="/strategies" component={StrategiesPage} />
                <Route path="/risk" component={RiskPage} />
                <Route path="/audit" component={AuditPage} />
                <Route path="/settings" component={SettingsPage} />
                <Route>
                  <Redirect to="/trade" />
                </Route>
              </Switch>
            </Suspense>
          </div>
        </div>
      </EngineProvider>
    </StatusProvider>
  );
}