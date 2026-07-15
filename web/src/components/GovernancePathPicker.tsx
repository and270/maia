import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowUp,
  ChevronRight,
  File,
  Folder,
  FolderOpen,
  Search,
  Server,
  X,
} from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Input } from "@/components/ui/input";
import {
  api,
  type GovernanceServerPathEntry,
  type GovernanceServerPathsResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export function GovernancePathPicker({
  initialPath,
  onClose,
  onSelect,
}: {
  initialPath: string;
  onClose: () => void;
  onSelect: (path: string) => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef(0);
  const [browser, setBrowser] = useState<GovernanceServerPathsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const load = useCallback(async (path?: string) => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError("");
    setQuery("");
    setSelectedFile(null);
    try {
      const response = await api.browseGovernanceServerPaths(path);
      if (requestId !== requestIdRef.current) return;
      setBrowser(response);
      setSelectedFile(response.selected_path);
    } catch (loadError) {
      if (requestId !== requestIdRef.current) return;
      setError(readableApiError(loadError));
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load(initialPath.trim() || undefined);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [initialPath, load]);

  useEffect(() => {
    const previousActive = document.activeElement as HTMLElement | null;
    dialogRef.current?.querySelector<HTMLButtonElement>("[data-close]")?.focus();

    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      requestIdRef.current += 1;
      window.removeEventListener("keydown", handleKey);
      document.body.style.overflow = previousOverflow;
      previousActive?.focus?.();
    };
  }, [onClose]);

  const visibleEntries = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return browser?.entries ?? [];
    return (browser?.entries ?? []).filter((entry) =>
      entry.name.toLocaleLowerCase().includes(needle),
    );
  }, [browser?.entries, query]);

  const selectAndClose = (path: string) => {
    onSelect(path);
    onClose();
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-stretch justify-center bg-background/85 backdrop-blur-sm sm:items-center sm:p-4"
      onClick={(event) => event.target === event.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="governance-path-picker-title"
    >
      <div
        ref={dialogRef}
        className="flex h-[100dvh] w-full flex-col border-border bg-card shadow-2xl sm:h-auto sm:max-h-[85vh] sm:max-w-3xl sm:border"
      >
        <header className="flex items-start gap-3 border-b border-border p-4 sm:p-5">
          <div className="mt-0.5 text-primary" aria-hidden>
            <Server className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <h2
              id="governance-path-picker-title"
              className="font-display text-sm uppercase tracking-wider text-foreground"
            >
              Select a server file or folder
            </h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Browse the filesystem visible to Maia. Nothing is uploaded or copied.
            </p>
          </div>
          <Button
            data-close
            ghost
            size="icon"
            onClick={onClose}
            aria-label="Close server path browser"
          >
            <X className="h-4 w-4" />
          </Button>
        </header>

        {browser && (
          <div className="space-y-3 border-b border-border px-4 py-3 sm:px-5">
            <div className="flex gap-2 overflow-x-auto pb-1" aria-label="Server locations">
              {browser.locations.map((location) => (
                <Button
                  key={`${location.label}:${location.path}`}
                  size="sm"
                  outlined
                  className="h-8 shrink-0 normal-case"
                  onClick={() => void load(location.path)}
                  title={location.path}
                >
                  {location.label}
                </Button>
              ))}
            </div>

            <nav
              className="flex min-h-8 items-center gap-1 overflow-x-auto font-mono-ui text-xs"
              aria-label="Current server path"
            >
              {browser.breadcrumbs.map((crumb, index) => (
                <div key={crumb.path} className="flex shrink-0 items-center gap-1">
                  {index > 0 && (
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                  )}
                  <button
                    type="button"
                    className="px-1 py-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    onClick={() => void load(crumb.path)}
                    title={crumb.path}
                  >
                    {crumb.label}
                  </button>
                </div>
              ))}
            </nav>

            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter this folder"
                className="h-8 pl-8"
                aria-label="Filter files and folders"
              />
            </div>
          </div>
        )}

        <main className="min-h-0 flex-1 overflow-y-auto" aria-live="polite">
          {loading && (
            <div className="flex min-h-56 items-center justify-center gap-2 text-sm text-muted-foreground">
              <Spinner /> Loading server paths…
            </div>
          )}

          {!loading && error && (
            <div className="mx-4 my-5 border border-destructive/40 bg-destructive/5 p-4 sm:mx-5">
              <p className="text-sm font-semibold text-destructive">This path cannot be opened</p>
              <p className="mt-1 break-words text-xs leading-5 text-muted-foreground">{error}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" outlined onClick={() => void load()}>
                  Open a default location
                </Button>
                <Button size="sm" ghost onClick={onClose}>
                  Enter the path manually
                </Button>
              </div>
            </div>
          )}

          {!loading && !error && browser && (
            <div className="divide-y divide-border">
              {browser.parent_path && (
                <PathRow
                  entry={{ name: "Parent folder", path: browser.parent_path, kind: "directory" }}
                  secondary="Go up one level"
                  onClick={() => void load(browser.parent_path ?? undefined)}
                  parent
                />
              )}
              {visibleEntries.map((entry) => (
                <PathRow
                  key={entry.path}
                  entry={entry}
                  selected={selectedFile === entry.path}
                  onClick={() => {
                    if (entry.kind === "directory") {
                      void load(entry.path);
                    } else {
                      setSelectedFile(entry.path);
                    }
                  }}
                />
              ))}
              {visibleEntries.length === 0 && (
                <div className="p-8 text-center text-sm text-muted-foreground">
                  {query ? "No matching files or folders." : "This folder is empty."}
                </div>
              )}
              {browser.truncated && !query && (
                <p className="border-t border-border p-3 text-center text-xs text-muted-foreground">
                  Showing the first 500 entries in this folder.
                </p>
              )}
            </div>
          )}
        </main>

        <footer className="border-t border-border bg-card p-3 sm:px-5">
          {browser && !error ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0 text-xs text-muted-foreground">
                <span className="block font-semibold text-foreground">
                  {selectedFile ? "Selected file" : "Current folder"}
                </span>
                <span className="block truncate font-mono-ui" title={selectedFile ?? browser.current_path}>
                  {selectedFile ?? browser.current_path}
                </span>
              </div>
              <div className="flex shrink-0 flex-col-reverse gap-2 sm:flex-row">
                <Button outlined onClick={onClose}>Cancel</Button>
                {selectedFile && (
                  <Button outlined onClick={() => selectAndClose(browser.current_path)}>
                    Use current folder
                  </Button>
                )}
                <Button onClick={() => selectAndClose(selectedFile ?? browser.current_path)}>
                  {selectedFile ? "Use selected file" : "Use current folder"}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex justify-end">
              <Button outlined onClick={onClose}>Cancel</Button>
            </div>
          )}
        </footer>
      </div>
    </div>,
    document.body,
  );
}

function PathRow({
  entry,
  onClick,
  parent = false,
  secondary,
  selected = false,
}: {
  entry: GovernanceServerPathEntry;
  onClick: () => void;
  parent?: boolean;
  secondary?: string;
  selected?: boolean;
}) {
  const Icon = parent ? ArrowUp : entry.kind === "directory" ? Folder : File;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={entry.kind === "file" ? selected : undefined}
      className={cn(
        "flex w-full items-center gap-3 px-4 py-3 text-left transition-colors sm:px-5",
        "hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
        selected && "bg-primary/10",
      )}
    >
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm text-foreground">{entry.name}</span>
        <span className="block truncate font-mono-ui text-[0.7rem] text-muted-foreground">
          {secondary ?? entry.path}
        </span>
      </span>
      {entry.kind === "directory" && !parent ? (
        <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      ) : null}
      {selected && <span className="text-xs font-semibold text-primary">Selected</span>}
    </button>
  );
}

function readableApiError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const jsonStart = message.indexOf("{");
  if (jsonStart >= 0) {
    try {
      const payload = JSON.parse(message.slice(jsonStart)) as { detail?: string };
      if (payload.detail) return payload.detail;
    } catch {
      // Fall through to the original message.
    }
  }
  return message;
}
