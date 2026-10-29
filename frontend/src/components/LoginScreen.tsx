import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { ViewBounds } from "../map/MapView";
import { useAuth } from "../auth/AuthProvider";
import { loadGoogleIdentity } from "../auth/google";
import { useServerWarmup } from "../lib/useServerWarmup";
import { MapSheet } from "../map/MapSheet";
import { ApiError } from "../api/client";
import { ErrorNote } from "./ErrorNote";

const MapView = lazy(() => import("../map/MapView").then((m) => ({ default: m.MapView })));
const NO_LAYERS = { rgb: false, classes: false, polygons: false, reference: false };

export function LoginScreen() {
  const { loginWithGoogle, endReason, api } = useAuth();
  const server = useServerWarmup(api);
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "";
  const button = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<unknown>(null);
  const [gsiFailed, setGsiFailed] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  const [view, setView] = useState<ViewBounds | null>(null);
  // O callback do Google é registrado uma vez; a ref evita fechar sobre um login velho
  const login = useRef(loginWithGoogle);
  login.current = loginWithGoogle;
  // Clique em "entrar" com a API ainda dormindo: o POST falha por rede. A
  // credencial do Google vale ~1 h, então guardamos e refazemos quando acordar.
  const serverRef = useRef(server);
  serverRef.current = server;
  const pending = useRef<string | null>(null);

  useEffect(() => {
    const credential = pending.current;
    if (!credential) return;
    if (server === "ready") {
      pending.current = null;
      login.current(credential).catch((e) => {
        setError(e);
        setSigningIn(false);
      });
    } else if (server === "down") {
      pending.current = null;
      setSigningIn(false);
    }
  }, [server]);

  useEffect(() => {
    let alive = true;
    loadGoogleIdentity()
      .then((gsi) => {
        if (!alive || !button.current) return;
        gsi.initialize({
          client_id: clientId,
          callback: ({ credential }) => {
            setSigningIn(true);
            setError(null);
            login.current(credential).catch((e) => {
              if (e instanceof ApiError && e.kind === "network" && serverRef.current !== "ready") {
                pending.current = credential; // refeito quando /health responder
                return;
              }
              setError(e);
              setSigningIn(false);
            });
          },
          auto_select: false,
          cancel_on_tap_outside: true,
          ux_mode: "popup",
          use_fedcm_for_button: true,
        });
        gsi.renderButton(button.current, {
          type: "standard",
          theme: "outline",
          size: "large",
          text: "continue_with",
          shape: "rectangular",
          locale: "pt-BR",
          width: 280,
        });
      })
      .catch(() => alive && setGsiFailed(true));
    return () => {
      alive = false;
    };
  }, [clientId]);

  return (
    <div className="login">
      <section className="login__intro">
        <p className="bar__brand">
          Candidatas a <span className="bar__product">café</span>
        </p>
        <h1 className="login__title">Onde pode haver café nesta imagem de satélite?</h1>
        <p className="login__lead">
          Envie uma cena Sentinel-2 multiespectral. O servidor calcula NDVI, NDWI e SAVI, separa água, solo exposto e
          mata fechada, e desenha os talhões que podem ser café, com a área de cada um em hectares.
        </p>
        <p className="login__lead">
          O resultado são áreas candidatas: nada aqui foi conferido em campo, e o assistente responde só com os números
          do processamento.
        </p>

        {endReason === "expired" && (
          <p className="note" role="status">
            Sua sessão expirou. Entre de novo para continuar.
          </p>
        )}

        <div className="login__action">
          {!clientId ? (
            <ErrorNote message="Login indisponível: VITE_GOOGLE_CLIENT_ID não configurado neste build." />
          ) : gsiFailed ? (
            <ErrorNote message="Não foi possível carregar o login do Google. Verifique bloqueadores de conteúdo e recarregue a página." />
          ) : (
            <div ref={button} className="login__google" aria-busy={signingIn} />
          )}
          {signingIn && (
            <p className="note" role="status">
              {server === "ready" || server === "checking"
                ? "Validando o login no servidor…"
                : "Login recebido. Esperando o servidor acordar para validá-lo (até 1 minuto)…"}
            </p>
          )}
          {server === "waking" && !signingIn && (
            <p className="note" role="status">
              O servidor gratuito estava dormindo e está acordando (leva até 1 minuto). Você já pode clicar em entrar: o login é concluído quando ele responder.
            </p>
          )}
          {server === "down" && error == null && (
            <ErrorNote message="A API não respondeu em 90 segundos. Seguimos tentando a cada 15 s; se persistir, o serviço pode estar fora do ar." />
          )}
          {error != null && <ErrorNote error={error} />}
        </div>

        <p className="login__fine">
          Guardamos seu nome e e-mail do Google para separar suas análises das de outros usuários. Imagens e resultados
          são apagados em até 24 h, ou antes se o servidor gratuito reiniciar (ele dorme após 15 min sem uso); a
          conta, após 30 dias sem uso.
        </p>
      </section>

      <div className="login__map">
        <MapSheet summary={null} view={view}>
          <Suspense fallback={null}>
            <MapView
              analysisId={null}
              coordinates={null}
              rgb={null}
              classes={null}
              polygons={null}
              layers={NO_LAYERS}
              focusPolygon={null}
              interactive={false}
              onViewChange={setView}
            />
          </Suspense>
        </MapSheet>
      </div>
    </div>
  );
}
