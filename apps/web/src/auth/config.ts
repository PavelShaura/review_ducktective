/**
 * Настройки провайдера личности.
 *
 * Адрес realm и клиент задаются сборкой: фронт раздаётся статикой и своих
 * секретов не имеет — публичный клиент с PKCE именно для этого и заведён.
 */
export const oidcConfig = {
  authority: import.meta.env.VITE_OIDC_ISSUER ?? "http://localhost:8081/realms/ducktective",
  client_id: import.meta.env.VITE_OIDC_CLIENT_ID ?? "ducktective-web",
  redirect_uri: window.location.origin + "/",
  post_logout_redirect_uri: window.location.origin + "/",
  response_type: "code",
  scope: "openid email profile",
  automaticSilentRenew: true,
  onSigninCallback: () => {
    window.history.replaceState({}, document.title, window.location.pathname);
  },
};
