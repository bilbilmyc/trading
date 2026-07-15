import { Suspense, lazy, useState } from "react";
import { Redirect, Route, Switch } from "wouter";

import { EngineProvider } from "./contexts/EngineContext";
import { StatusProvider } from "./contexts/StatusContext";
import { ThemeProvider } from "./contexts/ThemeContext";
import { LoadingFallback } from "./components/LoadingFallback";
import { Sidebar } from "./components/Sidebar";
import { Spine } from "./components/Spine";
import { CommandPalette } from "./components/CommandPalette";
import { StatusTicker } from "./components/StatusTicker";
import { StatusDrawer } from "./components/StatusDrawer";
import { TopTicker } from "./components/TopTicker";
import { Topbar } from "./components/Topbar";

// Code-split each page — initial bundle only ships the shell + first page.
const TradePage = lazy(() => import("./pages/TradePage").then((m) => ({ default: m.TradePage })));
const MarketsPage = lazy(() => import("./pages/MarketsPage").then((m) => ({ default: m.MarketsPage })));
const DataPage = lazy(() => import("./pages/DataPage").then((m) => ({ default: m.DataPage })));
const WatchlistPage = lazy(() => import("./pages/WatchlistPage").then((m) => ({ default: m.WatchlistPage })));
const PortfolioPage = lazy(() => import("./pages/PortfolioPage").then((m) => ({ default: m.PortfolioPage })));
const TradeHistoryPage = lazy(() => import("./pages/TradeHistoryPage").then((m) => ({ default: m.TradeHistoryPage })));
const StrategiesPage = lazy(() => import("./pages/StrategiesPage").then((m) => ({ default: m.StrategiesPage })));
const RiskPage = lazy(() => import("./pages/RiskPage").then((m) => ({ default: m.RiskPage })));
const AuditPage = lazy(() => import("./pages/AuditPage").then((m) => ({ default: m.AuditPage })));
const EventsPage = lazy(() => import("./pages/EventsPage").then((m) => ({ default: m.EventsPage })));
const BotMonitorPage = lazy(() => import("./pages/BotMonitorPage").then((m) => ({ default: m.BotMonitorPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })));

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <ThemeProvider>
      <StatusProvider>
        <EngineProvider>
          <div className="app-shell app-shell--with-sidebar app-shell--with-spine">
            {/* Ambient blur orbs — sit behind everything else. */}
            <div className="app-bg" aria-hidden="true" />

            <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

            <div className="app-main-row">
              {/* The Spine — 4px signature status strip between Sidebar and main. */}
              <Spine />

              <div className="app-main">
                <button
                  className="hamburger"
                  onClick={() => setSidebarOpen(true)}
                  aria-label="打开导航"
                >
                  ☰
                </button>
                <Topbar />
                <StatusTicker />
                <TopTicker />
                <Suspense fallback={<LoadingFallback title="加载中" hint="请稍候" />}>
                  <Switch>
                    <Route path="/" component={() => <Redirect to="/data" />} />
                    <Route path="/data" component={DataPage} />
                    <Route path="/watchlist" component={WatchlistPage} />
                    <Route path="/portfolio" component={PortfolioPage} />
                    <Route path="/trade" component={TradePage} />
                    <Route path="/trade-history" component={TradeHistoryPage} />
                    <Route path="/markets" component={MarketsPage} />
                    <Route path="/strategies" component={StrategiesPage } />
                    <Route path="/risk" component={RiskPage} />
                    <Route path="/audit" component={AuditPage} />
                    <Route path="/events" component={EventsPage} />
                    <Route path="/bot" component={BotMonitorPage} />
                    <Route path="/settings" component={SettingsPage} />
                    <Route path="/404" component={NotFoundPage} />
                    <Route>
                      <NotFoundPage />
                    </Route>
                  </Switch>
                </Suspense>
              </div>
            </div>

            <StatusDrawer />
            <CommandPalette />
          </div>
        </EngineProvider>
      </StatusProvider>
    </ThemeProvider>
  );
}
