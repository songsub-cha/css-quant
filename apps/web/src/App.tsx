import { Route, Routes } from "react-router";

import ProtectedRoute from "./components/ProtectedRoute";
import { useMeQuery } from "./hooks/useMeQuery";
import DashboardPage from "./pages/DashboardPage";
import GlossaryPage from "./pages/GlossaryPage";
import LoginPage from "./pages/LoginPage";
import RankingPage from "./pages/RankingPage";
import StrategyEditPage from "./pages/StrategyEditPage";
import StrategyListPage from "./pages/StrategyListPage";
import WatchlistPage from "./pages/WatchlistPage";

function App() {
  // Mounted once here so the auth store is populated before any route
  // (including ProtectedRoute) reads it.
  useMeQuery();

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/glossary" element={<GlossaryPage />} />
        <Route path="/rankings" element={<RankingPage />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
        <Route path="/strategies" element={<StrategyListPage />} />
        <Route path="/strategies/:id" element={<StrategyEditPage />} />
      </Route>
    </Routes>
  );
}

export default App;
