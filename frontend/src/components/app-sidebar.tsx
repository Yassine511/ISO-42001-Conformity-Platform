import {
  Building2,
  Check,
  ChevronsUpDown,
  ClipboardList,
  FileCheck2,
  LayoutDashboard,
  ListChecks,
  MessageSquareText,
  ShieldAlert,
  Sparkles,
  Wrench,
} from "lucide-react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ThemeToggle } from "@/components/theme-toggle";

export const NAV_ITEMS = [
  { segment: "", label: "Tableau de bord", icon: LayoutDashboard },
  { segment: "evaluations", label: "Évaluations & documents", icon: ListChecks },
  { segment: "chat", label: "Copilote", icon: MessageSquareText },
  { segment: "risk-register", label: "Registre des risques", icon: ShieldAlert },
  { segment: "soa", label: "Déclaration d'applicabilité", icon: ClipboardList },
  { segment: "remediation", label: "Remédiation", icon: Wrench },
] as const;

function isActive(pathname: string, orgId: string, segment: string): boolean {
  const base = `/organizations/${orgId}`;
  if (segment === "") return pathname === base || pathname === `${base}/`;
  // review workspace belongs to the évaluations section
  if (segment === "evaluations" && pathname.startsWith(`${base}/assessments`)) return true;
  return pathname.startsWith(`${base}/${segment}`);
}

export function AppSidebar() {
  const { orgId } = useParams<{ orgId: string }>();
  const { pathname } = useLocation();
  const orgs = useQuery({ queryKey: ["organizations"], queryFn: api.listOrganizations });
  const currentOrg = orgs.data?.find((o) => o.id === orgId);

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild tooltip="Accueil">
              <Link to="/">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <FileCheck2 className="size-4" aria-hidden="true" />
                </div>
                <div className="grid flex-1 leading-tight">
                  <span className="truncate text-sm font-semibold">Copilote ISO 42001</span>
                  <span className="truncate text-xs text-muted-foreground">INT102 · Teamwill</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton tooltip="Organisation" aria-label="Changer d'organisation">
                  <Building2 className="size-4" aria-hidden="true" />
                  <span className="truncate">{currentOrg?.name ?? "Organisation"}</span>
                  <ChevronsUpDown className="ml-auto size-4 opacity-60" aria-hidden="true" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
                <DropdownMenuLabel>Organisations</DropdownMenuLabel>
                {orgs.data?.map((org) => (
                  <DropdownMenuItem key={org.id} asChild>
                    <Link to={`/organizations/${org.id}`}>
                      <span className="truncate">{org.name}</span>
                      {org.id === orgId && (
                        <Check className="ml-auto size-4" aria-hidden="true" />
                      )}
                    </Link>
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link to="/">Gérer les organisations</Link>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Pilotage</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_ITEMS.map((item) => (
                <SidebarMenuItem key={item.segment}>
                  <SidebarMenuButton
                    asChild
                    isActive={isActive(pathname, orgId ?? "", item.segment)}
                    tooltip={item.label}
                  >
                    <Link
                      to={
                        item.segment
                          ? `/organizations/${orgId}/${item.segment}`
                          : `/organizations/${orgId}`
                      }
                    >
                      <item.icon aria-hidden="true" />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <div className="flex items-center justify-between gap-2 group-data-[collapsible=icon]:justify-center">
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
            <Sparkles className="size-3" aria-hidden="true" />
            Couche de confiance vérifiable
          </span>
          <ThemeToggle />
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
