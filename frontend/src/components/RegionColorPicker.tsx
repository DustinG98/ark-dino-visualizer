import { useState, useMemo, useRef, useEffect } from "react";
import type { ColorEntry, RegionMapping } from "@/lib/api";
import { cn } from "@/lib/utils";

interface RegionColorPickerProps {
  colors: ColorEntry[];
  regionColors: Record<number, number>;
  regions: RegionMapping[];
  usedRegions: Set<number>;
  onRegionColorChange: (regionId: number, colorId: number) => void;
}

export function RegionColorPicker({
  colors,
  regionColors,
  regions,
  usedRegions,
  onRegionColorChange,
}: RegionColorPickerProps) {
  const [openRegion, setOpenRegion] = useState<number | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const dropdownRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const buttonRefs = useRef<Map<number, HTMLButtonElement>>(new Map());

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (openRegion === null) return;
      const dropdown = dropdownRefs.current.get(openRegion);
      const button = buttonRefs.current.get(openRegion);
      if (
        dropdown &&
        !dropdown.contains(event.target as Node) &&
        button &&
        !button.contains(event.target as Node)
      ) {
        setOpenRegion(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [openRegion]);

  const filteredColors = useMemo(() => {
    if (!searchTerm) return colors;
    const term = searchTerm.toLowerCase();
    return colors.filter((c) =>
      c.Name.toLowerCase().includes(term)
    );
  }, [colors, searchTerm]);

  const colorMap = useMemo(() => {
    const map = new Map<number, ColorEntry>();
    for (const c of colors) {
      map.set(c.ID, c);
    }
    return map;
  }, [colors]);

  const availableRegions = useMemo(() => {
    return regions.filter((r) => usedRegions.has(r["Region ID"]));
  }, [regions, usedRegions]);

  if (availableRegions.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">
        No colorable regions detected for this dinosaur.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">Region Colors</h3>
      <div className="flex flex-col gap-2">
        {availableRegions.map((region) => {
          const regionId = region["Region ID"];
          const regionName = region["Mask Color"];
          const currentColorId = regionColors[regionId];
          const currentColor = colorMap.get(currentColorId);
          const isDropdownOpen = openRegion === regionId;

          return (
            <div key={regionId} className="relative">
              <label className="text-xs text-muted-foreground">
                {regionName}
              </label>
              <button
                ref={(el) => { if (el) buttonRefs.current.set(regionId, el); }}
                type="button"
                onClick={() => setOpenRegion(isDropdownOpen ? null : regionId)}
                className={cn(
                  "mt-1 flex w-full items-center gap-2 rounded-md border border-border bg-background px-2 py-1.5 text-left text-sm hover:bg-accent",
                  isDropdownOpen && "ring-2 ring-primary"
                )}
              >
                {currentColor && (
                  <span
                    className="h-5 w-5 rounded border"
                    style={{ backgroundColor: currentColor.Hex }}
                  />
                )}
                <span className="flex-1 truncate">
                  {currentColor?.Name ?? "Select..."}
                </span>
              </button>

              {isDropdownOpen && (
                <div
                  ref={(el) => { if (el) dropdownRefs.current.set(regionId, el); }}
                  className="absolute z-50 mt-1 max-h-64 min-w-[180px] rounded-md border border-border bg-background shadow-lg"
                  style={{
                    position: "absolute",
                    left: "0",
                    top: "100%",
                  }}
                >
                  <div className="sticky top-0 border-b border-border bg-background p-2">
                    <input
                      type="text"
                      placeholder="Search colors..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs"
                      autoFocus
                    />
                  </div>
                  <div className="max-h-48 overflow-y-auto p-1">
                    {filteredColors.map((color) => (
                      <button
                        key={color.ID}
                        type="button"
                        onClick={() => {
                          onRegionColorChange(regionId, color.ID);
                          setOpenRegion(null);
                          setSearchTerm("");
                        }}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent",
                          currentColorId === color.ID && "bg-accent"
                        )}
                      >
                        <span
                          className="h-4 w-4 rounded border"
                          style={{ backgroundColor: color.Hex }}
                        />
                        <span className="flex-1 truncate">{color.Name}</span>
                        <span className="text-muted-foreground">
                          #{color.ID}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
