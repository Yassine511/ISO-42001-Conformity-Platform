import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { Search } from "lucide-react";
import { Toaster } from "@/components/ui/sonner";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Button } from "@/components/ui/button";
import { AppSidebar, NAV_ITEMS, activeNavKey } from "@/components/app-sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { PageFade } from "@/components/motion";

/** Shell for every /organizations/:orgId route: sidebar + utility bar +
    content. The copilot route is full-bleed (its own internal scroll); other
    pages get the padded, width-capped main. Utility bar: 64px desktop, 56px
    mobile (spec §4.2). */
export function AppShell() {
  const { orgId } = useParams<{ orgId: string }>();
  const { pathname } = useLocation();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [commandOpen, setCommandOpen] = useState(false);

  const isChat = pathname.includes("/chat");
  const activeKey = activeNavKey(pathname, searchParams.toString(), orgId ?? "");
  const section = NAV_ITEMS.find((item) => item.key === activeKey)?.label ?? "Vue d'ensemble";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="flex h-svh flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background px-4 md:h-16">
          <SidebarTrigger className="-ml-1" aria-label="Basculer la barre latérale" />
          <Separator orientation="vertical" className="mr-1 !h-4" />
          <span className="truncate text-sm font-medium tracking-tight">{section}</span>
          <div className="ml-auto flex items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              className="h-10 gap-2 rounded-md px-3 text-muted-foreground sm:w-56 sm:justify-start"
              aria-label="Rechercher"
              onClick={() => setCommandOpen(true)}
            >
              <Search className="size-3.5" aria-hidden="true" />
              <span className="hidden sm:inline">Rechercher…</span>
              <kbd className="pointer-events-none ml-auto hidden rounded border bg-muted px-1.5 font-mono text-[10px] font-medium sm:inline-block">
                Ctrl K
              </kbd>
            </Button>
            <ThemeToggle />
          </div>
        </header>

        {isChat ? (
          <div className="min-h-0 flex-1">
            <Outlet />
          </div>
        ) : (
          <main className="min-h-0 flex-1 overflow-y-auto">
            <PageFade key={pathname} className="mx-auto w-full max-w-[1400px] px-4 py-6 md:px-7 md:py-8">
              <Outlet />
            </PageFade>
          </main>
        )}
      </SidebarInset>

      <CommandDialog
        open={commandOpen}
        onOpenChange={setCommandOpen}
        title="Navigation"
        description="Aller à une page"
      >
        <CommandInput placeholder="Aller à…" />
        <CommandList>
          <CommandEmpty>Aucun résultat.</CommandEmpty>
          <CommandGroup heading="Pages">
            {NAV_ITEMS.map((item) => (
              <CommandItem
                key={item.key}
                onSelect={() => {
                  setCommandOpen(false);
                  navigate(item.to(orgId ?? ""));
                }}
              >
                <item.icon aria-hidden="true" />
                {item.label}
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </CommandDialog>

      <Toaster richColors position="top-right" />
    </SidebarProvider>
  );
}
