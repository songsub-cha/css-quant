import { Routes, Route } from "react-router";
import Placeholder from "./pages/Placeholder";

function App() {
  return (
    <Routes>
      <Route path="/" element={<Placeholder />} />
    </Routes>
  );
}

export default App;
