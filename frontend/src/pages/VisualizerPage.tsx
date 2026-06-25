import { useEffect, useState } from "react";
import type { DinoInfo, ColorEntry, RegionMapping } from "@/lib/api";
import { fetchDinoList, fetchColors, fetchRegions } from "@/lib/api";
import { DinoGrid } from "@/components/DinoGrid";
import { DinoDetail } from "@/components/DinoDetail";
import { Loader2 } from "lucide-react";

export function VisualizerPage() {
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dinos, setDinos] = useState<DinoInfo[]>([]);
  const [colors, setColors] = useState<ColorEntry[]>([]);
  const [regions, setRegions] = useState<RegionMapping[]>([]);
  const [selectedDino, setSelectedDino] = useState<DinoInfo | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        setIsLoading(true);
        const [dinoList, colorList, regionList] = await Promise.all([
          fetchDinoList(),
          fetchColors(),
          fetchRegions(),
        ]);
        setDinos(dinoList);
        setColors(colorList);
        setRegions(regionList);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load data");
      } finally {
        setIsLoading(false);
      }
    }
    loadData();
  }, []);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="size-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-destructive">{error}</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border">
        <DinoGrid
          dinos={dinos}
          selectedDino={selectedDino}
          onSelectDino={setSelectedDino}
        />
      </div>
      <div className="flex-1 overflow-hidden">
        {selectedDino ? (
          <DinoDetail
            key={selectedDino.name}
            dino={selectedDino}
            colors={colors}
            regions={regions}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            Select a dinosaur to view and customize
          </div>
        )}
      </div>
    </div>
  );
}
