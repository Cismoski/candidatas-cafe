/**
 * Google Identity Services (botão "Fazer login com o Google").
 * O ID token devolvido pelo Google vai para o backend, que valida assinatura,
 * audiência (nosso client ID), emissor e e-mail verificado. O frontend nunca
 * confia no conteúdo do token.
 */

interface CredentialResponse {
  credential: string;
}

interface GoogleId {
  initialize(cfg: {
    client_id: string;
    callback: (r: CredentialResponse) => void;
    auto_select?: boolean;
    cancel_on_tap_outside?: boolean;
    ux_mode?: "popup" | "redirect";
    use_fedcm_for_button?: boolean;
  }): void;
  renderButton(el: HTMLElement, opts: Record<string, unknown>): void;
  disableAutoSelect(): void;
}

declare global {
  interface Window {
    google?: { accounts: { id: GoogleId } };
  }
}

const SRC = "https://accounts.google.com/gsi/client";
let loading: Promise<GoogleId> | null = null;

export function loadGoogleIdentity(): Promise<GoogleId> {
  if (window.google?.accounts?.id) return Promise.resolve(window.google.accounts.id);
  loading ??= new Promise<GoogleId>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = SRC;
    s.async = true;
    const fail = () => {
      loading = null; // permite tentar de novo
      s.remove();
      reject(new Error("gsi"));
    };
    s.onload = () => (window.google?.accounts?.id ? resolve(window.google.accounts.id) : fail());
    s.onerror = fail;
    document.head.appendChild(s);
  });
  return loading;
}
