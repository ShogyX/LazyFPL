import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import TeamPlanner from "./pages/TeamPlanner";
import ModelPerformance from "./pages/ModelPerformance";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/planner" replace />} />
        <Route path="/planner" element={<TeamPlanner />} />
        <Route path="/performance" element={<ModelPerformance />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/planner" replace />} />
      </Route>
    </Routes>
  );
}
