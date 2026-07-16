import { useState } from "react";
import {
  Building2,
  Check,
  ChevronsUpDown,
  ClipboardList,
  FileCheck2,
  FileText,
  LayoutDashboard,
  ListChecks,
  LogOut,
  MessageSquareText,
  ShieldAlert,
  UserCheck,
  UserPlus,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import { InviteDialog } from "@/components/invite-dialog";
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

export interface NavItem {
  key: string;
  label: string;
  icon: LucideIcon;
  group: string;
  /** Build the target path for an org. */
  to: (orgId: string) => string;
}

/** The stable product navigation — the mental model, not the route tree.
    Preuves and Évaluations share the frozen /evaluations route via query
    state; Revue humaine resolves at click time to the latest reviewable
    assessment (or to évaluations with an explanatory state). */
export const NAV_ITEMS: NavItem[] = [
  {
    key: "overview",
    label: "Vue d'ensemble",
    icon: LayoutDashboard,
    group: "Piloter",
    to: (orgId) => `/organizations/${orgId}`,
  },
  {
    key: "preuves",
    label: "Preuves",
    icon: FileText,
    group: "Évaluer",
    to: (orgId) => `/organizations/${orgId}/evaluations?vue=preuves`,
  },
  {
    key: "evaluations",
    label: "Évaluations",
    icon: ListChecks,
    group: "Évaluer",
    to: (orgId) => `/organizations/${orgId}/evaluations`,
  },
  {
    key: "review",
    label: "Revue humaine",
    icon: UserCheck,
    group: "Évaluer",
    to: (orgId) => `/organizations/${orgId}/evaluations?vue=revue`,
  },
  {
    key: "risks",
    label: "Risques",
    icon: ShieldAlert,
    group: "Traiter",
    to: (orgId) => `/organizations/${orgId}/risk-register`,
  },
  {
    key: "remediation",
    label: "Remédiation",
    icon: Wrench,
    group: "Traiter",
    to: (orgId) => `/organizations/${orgId}/remediation`,
  },
  {
    key: "soa",
    label: "Déclaration d'applicabilité",
    icon: ClipboardList,
    group: "Gouverner",
    to: (orgId) => `/organizations/${orgId}/soa`,
  },
  {
    key: "chat",
    label: "Copilote",
    icon: MessageSquareText,
    group: "Gouverner",
    to: (orgId) => `/organizations/${orgId}/chat`,
  },
];

const NAV_GROUPS = ["Piloter", "Évaluer", "Traiter", "Gouverner"] as const;

export function activeNavKey(pathname: string, search: string, orgId: string): string | null {
  const base = `/organizations/${orgId}`;
  if (pathname === base || pathname === `${base}/`) return "overview";
  if (pathname.startsWith(`${base}/assessments`)) return "review";
  if (pathname.startsWith(`${base}/evaluations`)) {
    const vue = new URLSearchParams(search).get("vue");
    if (vue === "preuves") return "preuves";
    if (vue === "revue") return "review";
    return "evaluations";
  }
  if (pathname.startsWith(`${base}/risk-register`)) return "risks";
  if (pathname.startsWith(`${base}/remediation`)) return "remediation";
  if (pathname.startsWith(`${base}/soa`)) return "soa";
  if (pathname.startsWith(`${base}/chat`)) return "chat";
  return null;
}

export function AppSidebar() {
  const { orgId = "" } = useParams<{ orgId: string }>();
  const { pathname } = useLocation();
  const [searchParams] = useSearchParams();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [inviteOpen, setInviteOpen] = useState(false);
  const orgs = useQuery({ queryKey: ["organizations"], queryFn: api.listOrganizations });
  // Revue humaine resolves to the latest assessment that has findings to
  // review; the list is already needed elsewhere so this stays cheap.
  const assessments = useQuery({
    queryKey: ["assessments", orgId],
    queryFn: () => api.listAssessments(orgId),
    enabled: !!orgId,
  });
  const currentOrg = orgs.data?.find((o) => o.id === orgId);
  const activeKey = activeNavKey(pathname, searchParams.toString(), orgId);

  const latestReviewable = assessments.data
    ?.filter((a) => a.findings_done > 0)
    .sort((a, b) => b.started_at.localeCompare(a.started_at))[0];

  const resolveTarget = (item: NavItem): string => {
    if (item.key === "review" && latestReviewable) {
      return `/organizations/${orgId}/assessments/${latestReviewable.id}`;
    }
    return item.to(orgId);
  };

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="gap-3 pb-1">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild tooltip="Accueil">
              <Link to="/">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-ink text-ink-foreground">
                  <FileCheck2 className="size-4" aria-hidden="true" />
                </div>
                <div className="grid flex-1 leading-tight">
                  <span className="truncate text-sm font-semibold tracking-tight">
                    Copilote ISO 42001
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    Gouvernance de l'IA
                  </span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton
                  tooltip="Organisation"
                  aria-label="Changer d'organisation"
                  className="border border-sidebar-border bg-background/60"
                >
                  <Building2 className="size-4" aria-hidden="true" />
                  <span className="truncate font-medium">{currentOrg?.name ?? "Organisation"}</span>
                  <ChevronsUpDown className="ml-auto size-4 opacity-60" aria-hidden="true" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-60">
                <DropdownMenuLabel>Organisations</DropdownMenuLabel>
                {orgs.data?.map((org) => (
                  <DropdownMenuItem key={org.id} asChild>
                    <Link to={`/organizations/${org.id}`}>
                      <span className="truncate">{org.name}</span>
                      {org.id === orgId && <Check className="ml-auto size-4" aria-hidden="true" />}
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
        {NAV_GROUPS.map((group) => (
          <SidebarGroup key={group} className="py-1">
            <SidebarGroupLabel className="text-[11px] tracking-[0.14em] uppercase">
              {group}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV_ITEMS.filter((item) => item.group === group).map((item) => (
                  <SidebarMenuItem key={item.key}>
                    <SidebarMenuButton
                      asChild
                      isActive={activeKey === item.key}
                      tooltip={item.label}
                      className="data-[active=true]:bg-ink data-[active=true]:font-medium data-[active=true]:text-ink-foreground"
                    >
                      <Link to={resolveTarget(item)}>
                        <item.icon aria-hidden="true" />
                        <span className="whitespace-normal">{item.label}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter>
        <p className="px-3 py-2 text-xs leading-relaxed text-muted-foreground group-data-[collapsible=icon]:hidden">
          L'IA propose, le code vérifie chaque citation, un humain confirme chaque verdict.
        </p>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton
                  size="lg"
                  tooltip="Compte"
                  aria-label="Menu du compte"
                  className="border border-sidebar-border bg-background/60"
                >
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-full border bg-muted text-xs font-semibold uppercase">
                    {(user?.display_name ?? "?").slice(0, 1)}
                  </div>
                  <div className="grid flex-1 leading-tight">
                    <span className="truncate text-sm font-medium">
                      {user?.display_name ?? "Compte"}
                    </span>
                    <span className="truncate text-xs text-muted-foreground">{user?.email}</span>
                  </div>
                  <ChevronsUpDown className="ml-auto size-4 opacity-60" aria-hidden="true" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" side="top" className="w-60">
                <DropdownMenuItem onSelect={() => setInviteOpen(true)}>
                  <UserPlus className="size-4" aria-hidden="true" />
                  Inviter un membre
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={async () => {
                    await logout();
                    navigate("/login", { replace: true });
                  }}
                >
                  <LogOut className="size-4" aria-hidden="true" />
                  Se déconnecter
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <InviteDialog orgId={orgId} open={inviteOpen} onOpenChange={setInviteOpen} />
    </Sidebar>
  );
}
