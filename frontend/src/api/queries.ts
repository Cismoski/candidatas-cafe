import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthProvider";
import { ApiError } from "./client";
import type { Analysis, AnalysisItem, AnalysisStatus, DownloadName } from "./types";

export const POLL_MS = 2500;

const isActive = (s: AnalysisStatus) => s === "pending" || s === "processing";

/** Não repete erros que não mudam com retry (4xx); repete falhas de rede/5xx. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

export const keys = {
  list: ["analyses"] as const,
  one: (id: string) => ["analyses", id] as const,
  file: (id: string, name: DownloadName) => ["analyses", id, "file", name] as const,
};

export function useAnalyses() {
  const { api } = useAuth();
  return useQuery({
    queryKey: keys.list,
    queryFn: ({ signal }) => api.listAnalyses(signal),
    // Enquanto houver análise na fila, a lista também atualiza o status
    refetchInterval: (q) => (q.state.data?.some((a) => isActive(a.status)) ? POLL_MS : false),
    retry: shouldRetry,
  });
}

export function useAnalysis(id: string | null) {
  const { api } = useAuth();
  const qc = useQueryClient();
  return useQuery({
    queryKey: keys.one(id ?? ""),
    enabled: id !== null,
    queryFn: async ({ signal }) => {
      const a = await api.getAnalysis(id as string, signal);
      // Mantém a lista coerente sem esperar o próximo refetch dela
      qc.setQueryData<AnalysisItem[]>(keys.list, (list) =>
        list?.map((x) => (x.id === a.id ? { ...x, status: a.status, error: a.error } : x)),
      );
      return a;
    },
    refetchInterval: (q) => (q.state.data && isActive(q.state.data.status) ? POLL_MS : false),
    retry: shouldRetry,
  });
}

export interface NewAnalysis {
  primary: File;
  scl?: File | null;
  secondary?: File | null;
  title?: string;
  idempotencyKey: string;
}

export function useCreateAnalysis() {
  const { api } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (n: NewAnalysis) => {
      const form = new FormData();
      form.append("primary", n.primary);
      if (n.scl) form.append("scl", n.scl);
      if (n.secondary) form.append("secondary", n.secondary);
      if (n.title?.trim()) form.append("title", n.title.trim());
      return api.createAnalysis(form, n.idempotencyKey);
    },
    onSuccess: (a: Analysis) => {
      qc.setQueryData(keys.one(a.id), a);
      qc.setQueryData<AnalysisItem[]>(keys.list, (list) =>
        list ? [a, ...list.filter((x) => x.id !== a.id)] : [a],
      );
      void qc.invalidateQueries({ queryKey: keys.list, exact: true });
    },
  });
}

export function useDeleteAnalysis() {
  const { api } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteAnalysis(id),
    onSuccess: (_: void, id: string) => {
      qc.removeQueries({ queryKey: keys.one(id) });
      qc.setQueryData<AnalysisItem[]>(keys.list, (list) => list?.filter((x) => x.id !== id));
    },
  });
}

/** Arquivo de saída autenticado (o Bearer não vai em <img src>, então baixamos o blob). */
export function useAnalysisFile(id: string, name: DownloadName, enabled: boolean) {
  const { api } = useAuth();
  return useQuery({
    queryKey: keys.file(id, name),
    queryFn: ({ signal }) => api.file(id, name, signal),
    enabled,
    staleTime: Number.POSITIVE_INFINITY, // produtos de uma análise concluída não mudam
    gcTime: 5 * 60_000,
    retry: shouldRetry,
  });
}
