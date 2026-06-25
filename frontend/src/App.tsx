import { useState } from "react";
import { Routes, Route } from "react-router-dom";
import { Sidebar } from "@/components/Sidebar";
import { HomePage } from "@/pages/HomePage";
import { VisualizerPage } from "@/pages/VisualizerPage";
import { cn } from "@/lib/utils";

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="min-h-screen overflow-hidden">
      <Sidebar isOpen={sidebarOpen} onToggle={() => setSidebarOpen(!sidebarOpen)} />

      <div
        className={cn(
          "h-screen overflow-x-hidden transition-all duration-300",
          sidebarOpen
            ? "ml-0 md:ml-64"
            : "ml-0 md:ml-16"
        )}
      >
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/visualizer" element={<VisualizerPage />} />
        </Routes>
      </div>
    </div>
  );
}

export default App;
