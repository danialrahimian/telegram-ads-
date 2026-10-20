import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { Direction } from "radix-ui";
import { lazy, Suspense, useEffect } from "react";
import { createBrowserRouter, Outlet, RouterProvider } from "react-router";
import { AccountLayout } from "@/components/layout/account-layout";
import { AppShell } from "@/components/layout/app-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/hooks/use-theme";
import { ApiError, onUnauthorized } from "@/lib/api";
import { keys, useMe } from "@/lib/queries";
import type { Me } from "@/lib/types";
import { LoginPage } from "@/pages/login";

const OverviewPage = lazy(() => import("@/pages/overview"));
const GlobalSettingsPage = lazy(() => import("@/pages/global-settings"));
const AccountNewPage = lazy(() => import("@/pages/account-new"));
const NotFoundPage = lazy(() => import("@/pages/not-found"));
const DashboardPage = lazy(() => import("@/pages/account/dashboard"));
const AdsPage = lazy(() => import("@/pages/account/ads"));
const AdDetailPage = lazy(() => import("@/pages/account/ad-detail"));
const AdNewPage = lazy(() => import("@/pages/account/ad-new"));
const ProposalsPage = lazy(() => import("@/pages/account/proposals"));
const TextsPage = lazy(() => import("@/pages/account/texts"));
const SalesPage = lazy(() => import("@/pages/account/sales"));
const AnalysisPage = lazy(() => import("@/pages/account/analysis"));
const ActivityPage = lazy(() => import("@/pages/account/activity"));
const AccountSettingsPage = lazy(() => import("@/pages/account/settings"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2_000,
      refetchOnWindowFocus: true,
      retry: (n, e) => !(e instanceof ApiError && [401, 403, 404, 422].includes(e.status)) && n < 2,
    },
  },
});

function PageFallback() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-64" />
    </div>
  );
}

function AuthGate() {
  const qc = useQueryClient();
  const { data, isLoading, error, refetch } = useMe();

  useEffect(
    () =>
      onUnauthorized(() => {
        qc.setQueryData<Me>(keys.me, (old) => (old ? { ...old, authenticated: false } : old));
      }),
    [qc],
  );

  if (isLoading) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <div className="size-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }
  if (error || !data) return <LoginPage me={undefined} error={error} retry={() => refetch()} />;
  if (!data.authenticated) return <LoginPage me={data} />;
  return (
    <Suspense fallback={<PageFallback />}>
      <Outlet />
    </Suspense>
  );
}

const router = createBrowserRouter([
  {
    element: <AuthGate />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <OverviewPage /> },
          { path: "settings", element: <GlobalSettingsPage /> },
          { path: "accounts/new", element: <AccountNewPage /> },
          {
            path: "accounts/:slug",
            element: <AccountLayout />,
            children: [
              { index: true, element: <DashboardPage /> },
              { path: "ads", element: <AdsPage /> },
              { path: "ads/new", element: <AdNewPage /> },
              { path: "ads/:adId", element: <AdDetailPage /> },
              { path: "proposals", element: <ProposalsPage /> },
              { path: "texts", element: <TextsPage /> },
              { path: "sales", element: <SalesPage /> },
              { path: "analysis", element: <AnalysisPage /> },
              { path: "activity", element: <ActivityPage /> },
              { path: "settings", element: <AccountSettingsPage /> },
            ],
          },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);

export function App() {
  return (
    <ThemeProvider>
      <Direction.Provider dir="rtl">
        <QueryClientProvider client={queryClient}>
          <TooltipProvider>
            <RouterProvider router={router} />
            <Toaster />
          </TooltipProvider>
        </QueryClientProvider>
      </Direction.Provider>
    </ThemeProvider>
  );
}
