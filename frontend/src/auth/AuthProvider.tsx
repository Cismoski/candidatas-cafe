import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { API_URL, ApiClient } from "../api/client";
import type { User } from "../api/types";
import { clear, fromLogin, isValid, load, type StoredSession, save } from "./session";

export type EndReason = "expired" | "logout" | null;

interface AuthState {
  user: User | null;
  api: ApiClient;
  /** Por que a última sessão terminou (mostra "sessão expirada" no login). */
  endReason: EndReason;
  loginWithGoogle: (credential: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children, baseUrl = API_URL }: { children: ReactNode; baseUrl?: string }) {
  const queryClient = useQueryClient();
  const [session, setSession] = useState<StoredSession | null>(() => load());
  const [endReason, setEndReason] = useState<EndReason>(null);
  // Ref para o cliente ler o token atual sem ser recriado a cada login
  const sessionRef = useRef(session);
  sessionRef.current = session;

  const end = useCallback(
    (reason: EndReason) => {
      clear();
      setSession(null);
      setEndReason(reason);
      // Nada do usuário anterior pode sobreviver no cache (isolamento na UI)
      queryClient.clear();
    },
    [queryClient],
  );

  const api = useMemo(
    () =>
      new ApiClient(
        baseUrl,
        () => (isValid(sessionRef.current) ? sessionRef.current.token : null),
        () => end("expired"),
      ),
    [baseUrl, end],
  );

  // Expiração local: encerra no instante em que o JWT vence, sem esperar um 401
  useEffect(() => {
    if (!session) return;
    const ms = session.expiresAt - Date.now() - 30_000;
    const t = window.setTimeout(() => end("expired"), Math.max(0, ms));
    return () => window.clearTimeout(t);
  }, [session, end]);

  const loginWithGoogle = useCallback(
    async (credential: string) => {
      const s = fromLogin(await api.loginWithGoogle(credential));
      queryClient.clear();
      save(s);
      setEndReason(null);
      setSession(s);
    },
    [api, queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout(); // revoga o jti no backend
    } catch {
      /* mesmo offline, a sessão local é encerrada */
    } finally {
      window.google?.accounts.id.disableAutoSelect();
      end("logout");
    }
  }, [api, end]);

  const value = useMemo(
    () => ({ user: session?.user ?? null, api, endReason, loginWithGoogle, logout }),
    [session, api, endReason, loginWithGoogle, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth fora do AuthProvider");
  return ctx;
}
