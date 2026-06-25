import { Link } from "react-router-dom";
import { Dna, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function HomePage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-8 p-8">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight">ARK Dino Visualizer</h1>
        <p className="mt-4 text-lg text-muted-foreground">
          Customize dinosaur region colors for ARK: Survival Ascended
        </p>
      </div>

      <div className="flex flex-col items-center gap-4">
        <Link to="/visualizer">
          <Button size="lg" className="gap-2">
            <Dna className="size-5" />
            Open Visualizer
            <ArrowRight className="size-5" />
          </Button>
        </Link>
      </div>

      <div className="mt-8 grid max-w-2xl grid-cols-1 gap-6 text-center sm:grid-cols-2">
        <div className="rounded-lg border border-border p-4">
          <h3 className="font-semibold">Browse Dinosaurs</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Search through all available dinosaurs and view their default colors
          </p>
        </div>
        <div className="rounded-lg border border-border p-4">
          <h3 className="font-semibold">Customize Colors</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Change region colors for each body part using the interactive color picker
          </p>
        </div>
      </div>
    </div>
  );
}
