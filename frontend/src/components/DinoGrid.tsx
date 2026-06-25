import { useState, useMemo } from "react";
import { Search } from "lucide-react";
import type { DinoInfo } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface DinoGridProps {
  dinos: DinoInfo[];
  selectedDino: DinoInfo | null;
  onSelectDino: (dino: DinoInfo) => void;
}

export function DinoGrid({ dinos, selectedDino, onSelectDino }: DinoGridProps) {
  const [searchTerm, setSearchTerm] = useState("");

  const filteredDinos = useMemo(() => {
    if (!searchTerm) return [];
    const _term = searchTerm.toLowerCase();
    return dinos
      .filter((dino) =>
        dino.searchTerms.some((term) => term.includes(_term))
      )
      .slice(0, 6);
  }, [dinos, searchTerm]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border p-4">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="text"
            placeholder="Search dinos..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <div className="divide-y divide-border">
          {filteredDinos.map((dino) => (
            <div
              key={dino.name}
              className={cn(
                "flex cursor-pointer items-center gap-3 p-3 transition-colors",
                selectedDino?.name === dino.name
                  ? "bg-accent"
                  : "hover:bg-muted"
              )}
              onClick={() => onSelectDino(dino)}
            >
              <img
                src={`/dinos/images/${dino.imageFile}`}
                alt={dino.name}
                className="size-12 rounded-md object-cover bg-muted"
              />
              <span className="text-sm font-medium">{dino.name}</span>
            </div>
          ))}
        </div>

        {filteredDinos.length === 0 && (
          <div className="flex h-32 items-center justify-center">
            <p className="text-sm text-muted-foreground">
              {searchTerm ? "No dinosaurs found" : "Start typing to search"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}