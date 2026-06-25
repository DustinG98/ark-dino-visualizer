import { NavLink } from "react-router-dom";
import { PanelLeftClose, PanelLeft, Dna, Home } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
}

export function Sidebar({ isOpen, onToggle }: SidebarProps) {
  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={onToggle}
        />
      )}

      <div
        className={cn(
          "fixed left-0 top-0 z-40 flex h-full flex-col border-r border-border bg-background transition-all duration-300",
          isOpen
            ? "inset-0 w-full md:inset-auto md:w-64"
            : "-left-16 w-16 md:left-0"
        )}
      >
        <div className="flex h-14 items-center border-b border-border px-2">
          {isOpen ? (
            <>
              <span className="flex-1 text-lg font-semibold tracking-tight">Menu</span>
              <Button variant="ghost" size="icon" onClick={onToggle} className="shrink-0 md:hidden">
                <PanelLeftClose className="size-5" />
              </Button>
            </>
          ) : (
            <Button
              variant="ghost"
              size="icon"
              onClick={onToggle}
              className="mx-auto"
            >
              <PanelLeft className="size-5" />
            </Button>
          )}
        </div>

        <nav className="flex-1 overflow-auto p-2">
          <div className="space-y-1">
            <NavLink
              to="/"
              className={({ isActive }) =>
                cn(
                  "flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isOpen ? "gap-3" : "justify-center px-0",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )
              }
            >
              <Home className="size-5 shrink-0" />
              {isOpen && <span>Home</span>}
            </NavLink>

            <NavLink
              to="/visualizer"
              className={({ isActive }) =>
                cn(
                  "flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isOpen ? "gap-3" : "justify-center px-0",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )
              }
            >
              <Dna className="size-5 shrink-0" />
              {isOpen && <span>Dino Visualizer</span>}
            </NavLink>
          </div>
        </nav>
      </div>
    </>
  );
}
