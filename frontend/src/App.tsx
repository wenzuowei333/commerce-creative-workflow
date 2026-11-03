import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { ApiError, apiRequest, setCsrfToken } from "./api/client";
import { AppShell } from "./components/AppShell";
import { AssetsPage } from "./pages/AssetsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { LoginPage } from "./pages/LoginPage";
import { TemplatesPage } from "./pages/TemplatesPage";
import { WorkbenchPage } from "./pages/WorkbenchPage";

type Session = { user: { id: string; username: string }; csrf_token: string };

export function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const session = useQuery<Session | null>({
    queryKey: ["auth", "session"],
    queryFn: async () => {
      try {
        const data = await apiRequest<Session>("/auth/session");
        setCsrfToken(data.csrf_token);
        return data;
      } catch (error) {
        if (error instanceof ApiError && error.code === "authentication_required") {
          setCsrfToken(null);
          return null;
        }
        throw error;
      }
    },
    retry: false,
  });
  const logout = useMutation({
    mutationFn: () => apiRequest("/auth/logout", { method: "POST" }),
    onSettled: () => {
      setCsrfToken(null);
      queryClient.clear();
      navigate("/login", { replace: true });
    },
  });

  if (session.isPending) {
    return (
      <div className="empty-state" style={{ minHeight: "100vh", border: 0 }}>
        <LoaderCircle size={28} className="spin" />
        <p>正在载入工作台</p>
      </div>
    );
  }

  if (!session.data && location.pathname !== "/login") {
    return <Navigate to="/login" replace />;
  }

  if (session.data && location.pathname === "/login") {
    return <Navigate to="/" replace />;
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {session.data && (
        <Route
          element={
            <AppShell
              username={session.data.user.username}
              onLogout={() => logout.mutate()}
            />
          }
        >
          <Route index element={<WorkbenchPage />} />
          <Route path="assets" element={<AssetsPage />} />
          <Route path="templates" element={<TemplatesPage />} />
          <Route path="history" element={<HistoryPage />} />
        </Route>
      )}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
