import { useState } from "react";
import {
  ArrowLeft,
  Building2,
  Check,
  ChevronsUpDown,
  ClipboardList,
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
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import { MembersDialog } from "@/components/members-dialog";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
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
  const queryClient = useQueryClient();
  const [membersOpen, setMembersOpen] = useState(false);
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
  // Pending human decisions across all assessments — surfaced as the amber
  // count on « Revue humaine » (matches the design's nav badge).
  const pendingReviewCount = (assessments.data ?? []).reduce(
    (n, a) => n + Math.max(0, a.findings_done - a.reviewed_count),
    0,
  );

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
            <SidebarMenuButton size="lg" asChild tooltip="Retour à l'accueil">
              <Link to="/" aria-label="Retour à l'accueil">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-ink text-ink-foreground">
                  <ArrowLeft className="size-4" aria-hidden="true" />
                </div>
                <div className="grid flex-1 leading-tight">
                  <span className="truncate text-sm font-medium tracking-tight">
                    Retour à l'accueil
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    {currentOrg?.name ?? "Gouvernance de l'IA"}
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
        <SidebarGroup className="py-1">
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_ITEMS.map((item) => {
                const showCount = item.key === "review" && pendingReviewCount > 0;
                return (
                  <SidebarMenuItem key={item.key}>
                    <SidebarMenuButton
                      asChild
                      isActive={activeKey === item.key}
                      tooltip={item.label}
                      className="data-[active=true]:bg-ink data-[active=true]:font-medium data-[active=true]:text-ink-foreground"
                    >
                      <Link to={resolveTarget(item)}>
                        <item.icon aria-hidden="true" />
                        <span className="flex-1 whitespace-normal">{item.label}</span>
                        {showCount ? (
                          <span
                            className="ml-auto inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-warning px-1.5 font-mono text-[10px] font-bold text-warning-foreground group-data-[collapsible=icon]:hidden"
                            aria-label={`${pendingReviewCount} en attente`}
                          >
                            {pendingReviewCount}
                          </span>
                        ) : null}
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
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
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-ink text-xs font-semibold uppercase text-ink-foreground">
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
                <DropdownMenuItem onSelect={() => setMembersOpen(true)}>
                  <UserPlus className="size-4" aria-hidden="true" />
                  Membres et invitations
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

      <MembersDialog
        orgId={orgId}
        open={membersOpen}
        onOpenChange={setMembersOpen}
        onSelfRemoved={async () => {
          // this org now 404s for us — land on an org we still belong to
          const remaining = await api.listOrganizations();
          queryClient.setQueryData(["organizations"], remaining);
          navigate(remaining.length > 0 ? `/organizations/${remaining[0].id}` : "/", {
            replace: true,
          });
        }}
      />
    </Sidebar>
  );
}
