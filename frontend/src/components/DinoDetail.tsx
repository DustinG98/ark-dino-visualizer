import { useEffect, useRef, useState } from "react";
import { RotateCcw, Check } from "lucide-react";
import type { DinoInfo, ColorEntry, RegionMapping } from "@/lib/api";
import { fetchColoredDino } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { RegionColorPicker } from "./RegionColorPicker";

interface DinoDetailProps {
  dino: DinoInfo;
  colors: ColorEntry[];
  regions: RegionMapping[];
}

interface DinoState {
  regionColors: Record<number, number>;
  appliedColors: Record<number, number>;
  isLoading: boolean;
  hasError: boolean;
}

const NEUTRAL_COLOR_ID = 18;

function createNeutralRegionColors(): Record<number, number> {
  return { 0: NEUTRAL_COLOR_ID, 1: NEUTRAL_COLOR_ID, 2: NEUTRAL_COLOR_ID, 3: NEUTRAL_COLOR_ID, 4: NEUTRAL_COLOR_ID, 5: NEUTRAL_COLOR_ID };
}

export function DinoDetail({ dino, colors, regions }: DinoDetailProps) {
  const [dinoState, setDinoState] = useState<DinoState>(() => ({
    regionColors: createNeutralRegionColors(),
    appliedColors: createNeutralRegionColors(),
    isLoading: true,
    hasError: false,
  }));

  const imageUrlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadImage() {
      setDinoState((prev) => ({ ...prev, isLoading: true, hasError: false }));

      try {
        const blob = await fetchColoredDino(dino.imageFile, createNeutralRegionColors());
        if (cancelled) return;

        if (imageUrlRef.current) {
          URL.revokeObjectURL(imageUrlRef.current);
        }
        imageUrlRef.current = URL.createObjectURL(blob);

        setDinoState((prev) => ({ ...prev, isLoading: false }));
      } catch {
        if (!cancelled) {
          setDinoState((prev) => ({ ...prev, isLoading: false, hasError: true }));
        }
      }
    }

    loadImage();

    return () => {
      cancelled = true;
      if (imageUrlRef.current) {
        URL.revokeObjectURL(imageUrlRef.current);
        imageUrlRef.current = null;
      }
    };
  }, [dino]);

  useEffect(() => {
    if (!dinoState.isLoading) {
      loadRenderedImage();
    }
  }, [dinoState.appliedColors]);

  async function loadRenderedImage() {
    setDinoState((prev) => ({ ...prev, isLoading: true }));

    try {
      const blob = await fetchColoredDino(dino.imageFile, dinoState.appliedColors);

      if (imageUrlRef.current) {
        URL.revokeObjectURL(imageUrlRef.current);
      }
      imageUrlRef.current = URL.createObjectURL(blob);

      setDinoState((prev) => ({ ...prev, isLoading: false }));
    } catch {
      setDinoState((prev) => ({ ...prev, isLoading: false, hasError: true }));
    }
  }

  const handleRegionColorChange = (regionId: number, colorId: number) => {
    setDinoState((prev) => ({
      ...prev,
      regionColors: { ...prev.regionColors, [regionId]: colorId },
    }));
  };

  const handleApply = () => {
    setDinoState((prev) => ({
      ...prev,
      appliedColors: { ...prev.regionColors },
    }));
  };

  const handleReset = () => {
    const neutral = createNeutralRegionColors();
    setDinoState((prev) => ({
      ...prev,
      regionColors: neutral,
      appliedColors: neutral,
    }));
  };

  const hasChanges = JSON.stringify(dinoState.regionColors) !== JSON.stringify(dinoState.appliedColors);

  const usedRegionsSet = new Set(dino.usedRegions);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-col gap-2 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-lg font-semibold">{dino.name}</h2>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleReset}
          >
            <RotateCcw className="mr-1 size-4" />
            Reset
          </Button>
          <Button
            type="button"
            variant="default"
            size="sm"
            onClick={handleApply}
            disabled={!hasChanges}
          >
            <Check className="mr-1 size-4" />
            Apply
          </Button>
        </div>
      </div>

      <div className="flex flex-1 flex-col lg:flex-row">
        <div className="flex-1 overflow-auto bg-muted p-4">
          <div className="flex items-center justify-center">
            {dinoState.isLoading && (
              <div className="flex h-64 w-64 items-center justify-center rounded-lg bg-muted-foreground/10">
                <span className="text-muted-foreground">Loading...</span>
              </div>
            )}
            {dinoState.hasError && (
              <div className="flex h-64 w-64 items-center justify-center rounded-lg bg-destructive/10">
                <span className="text-destructive">Failed to load image</span>
              </div>
            )}
            {!dinoState.isLoading && !dinoState.hasError && imageUrlRef.current && (
              <img
                src={imageUrlRef.current}
                alt={dino.name}
                className="max-w-full rounded-lg shadow-lg"
                style={{ maxHeight: "calc(100vh - 280px)" }}
              />
            )}
          </div>
        </div>

        <div className="w-full border-t border-border bg-background p-4 lg:w-72 lg:border-t-0 lg:border-l">
          <RegionColorPicker
            colors={colors}
            regionColors={dinoState.regionColors}
            regions={regions}
            usedRegions={usedRegionsSet}
            onRegionColorChange={handleRegionColorChange}
          />
        </div>
      </div>
    </div>
  );
}
