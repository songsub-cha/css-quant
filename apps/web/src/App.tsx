import { Route, Routes } from "react-router";

import ProtectedRoute from "./components/ProtectedRoute";
import { useMeQuery } from "./hooks/useMeQuery";
import DashboardPage from "./pages/DashboardPage";
import LoginPage from "./pages/LoginPage";

function App() {
  // Mounted once here so the auth store is populated before any route
  // (including ProtectedRoute) reads it.
  useMeQuery();

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<DashboardPage />} />
      </Route>
    </Routes>
  );
}

export default App;
