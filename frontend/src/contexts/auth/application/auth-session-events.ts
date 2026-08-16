export const AUTHENTICATION_REQUIRED_EVENT =
  "enterprise-agent:authentication-required"

export function notifyAuthenticationRequired() {
  window.dispatchEvent(new Event(AUTHENTICATION_REQUIRED_EVENT))
}
