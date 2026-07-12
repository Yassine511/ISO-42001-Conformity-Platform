import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
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
import { AppSidebar, NAV_ITEMS } from "@/components/app-sidebar";

/** Shell for every /organizations/:orgId route: sidebar + header + content.
    The copilot route is full-bleed (its own internal scroll); other pages get
    the padded, width-capped main. */
export function AppShell() {
  const { orgId } = useParams<{ orgId: string }>();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [commandOpen, setCommandOpen] = useState(false);

  const isChat = pathname.includes("/chat");
  const section =
    NAV_ITEMS.find((item) =>
      item.segment === ""
        ? pathname === `/organizations/${orgId}`
        : pathname.startsWith(`/organizations/${orgId}/${item.segment}`) ||
          (item.segment === "evaluations" &&
            pathname.startsWith(`/organizations/${orgId}/assessments`)),
    )?.label ?? "Tableau de bord";

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
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger className="-ml-1" aria-label="Basculer la barre latérale" />
          <Separator orientation="vertical" className="mr-1 !h-4" />
          <span className="text-sm font-medium">{section}</span>
          <div className="ml-auto">
            <Button
              variant="outline"
              size="sm"
              className="gap-2 text-muted-foreground"
              onClick={() => setCommandOpen(true)}
            >
              <Search className="size-3.5" aria-hidden="true" />
              <span className="hidden sm:inline">Rechercher…</span>
              <kbd className="pointer-events-none hidden rounded border bg-muted px-1.5 font-mono text-[10px] font-medium sm:inline-block">
                Ctrl K
              </kbd>
            </Button>
          </div>
        </header>

        {isChat ? (
          <div className="min-h-0 flex-1">
            <Outlet />
          </div>
        ) : (
          <main className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8">
              <Outlet />
            </div>
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
                key={item.segment}
                onSelect={() => {
                  setCommandOpen(false);
                  navigate(
                    item.segment
                      ? `/organizations/${orgId}/${item.segment}`
                      : `/organizations/${orgId}`,
                  );
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
