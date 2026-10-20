import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post } from "@/api/client";
import type { LoginOut, Me } from "@/api/types";

export function useSession() {
  return useQuery<Me | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await get<Me>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (identifier: string) => post<LoginOut>("/auth/login", { identifier }),
    onSuccess: (data) => {
      qc.clear();
      qc.setQueryData(["me"], { user: data.user, active_target_id: data.active_target_id, auth_mode: data.auth_mode });
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post("/auth/logout"),
    onSettled: () => {
      qc.clear();
      qc.setQueryData(["me"], null);
    },
  });
}

/** The active target id from the session (refreshes /auth/me when targets change). */
export function useActiveTargetId(): string | null {
  const { data } = useSession();
  return data?.active_target_id ?? null;
}
