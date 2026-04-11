# OAuth Service

## Overview

The OAuth Service implements the OAuth 2.0 Authorization Code flow with PKCE (Proof Key for Code Exchange) for authenticating users with their Claude.ai accounts. It manages the complete flow: generating a code verifier/challenge pair, starting a local HTTP listener on a free port to capture the redirect callback, opening the user's browser to the authorization URL, exchanging the authorization code for tokens, and fetching the user's subscription profile. It supports both an automatic flow (browser redirect captured via localhost) and a manual flow (user copies and pastes the code) for environments where browser opening is not possible.

## Key Types / Key Concepts

```typescript
// The main service class
class OAuthService {
  private codeVerifier: string
  private authCodeListener: AuthCodeListener | null
  private port: number | null
  private manualAuthCodeResolver: ((code: string) => void) | null

  async startOAuthFlow(
    authURLHandler: (url: string, automaticUrl?: string) => Promise<void>,
    options?: {
      loginWithClaudeAi?: boolean
      inferenceOnly?: boolean
      expiresIn?: number
      orgUUID?: string
      loginHint?: string
      loginMethod?: string
      skipBrowserOpen?: boolean   // Used by SDK control protocol
    }
  ): Promise<OAuthTokens>

  handleManualAuthCodeInput(params: {
    authorizationCode: string
    state: string
  }): void

  cleanup(): void
}

// Token result returned to caller
type OAuthTokens = {
  accessToken: string
  refreshToken: string
  expiresAt: number        // Unix ms timestamp
  scopes: string[]
  subscriptionType: SubscriptionType | null
  rateLimitTier: RateLimitTier | null
  profile?: OAuthProfileResponse
  tokenAccount?: {
    uuid: string
    emailAddress: string
    organizationUuid?: string
  }
}
```

## Architecture

The OAuth service is split into focused modules:

**`index.ts` — OAuthService class**:
Orchestrates the entire flow. Constructs PKCE values, starts the local listener, opens the browser, races automatic vs. manual code arrival, calls the token exchange, fetches profile, and returns `OAuthTokens`. The `skipBrowserOpen` option allows the SDK control protocol to take over URL presentation.

**`client.ts`**:
All HTTP calls to Anthropic's OAuth endpoints:
- `buildAuthUrl()`: Constructs the authorization URL with PKCE parameters and state
- `exchangeCodeForTokens()`: POSTs the authorization code to the token endpoint
- `fetchProfileInfo()`: GETs the user's profile (subscription type, rate limit tier)
- `parseScopes()`: Parses the space-separated scopes string into an array

**`auth-code-listener.ts` — AuthCodeListener**:
A minimal HTTP server (`http.createServer`) that listens on a random free port. When the browser redirects to `localhost:{port}/oauth/callback?code=...&state=...`, the listener captures the code, validates state, and resolves the promise. Also serves success/error redirect pages to give the user visual confirmation.

**`crypto.ts`**:
PKCE cryptographic primitives:
- `generateCodeVerifier()`: Generates a 43-128 character random string
- `generateCodeChallenge(verifier)`: SHA-256 hashes and base64url-encodes the verifier
- `generateState()`: Generates a random state token for CSRF protection

**`getOauthProfile.ts`**:
Standalone utility for fetching the OAuth profile with an existing access token.

The manual flow path works by exposing `handleManualAuthCodeInput()` — when the user pastes the auth code into the terminal, the CLI calls this method, which resolves the same promise that the automatic listener is waiting on.

## Source Files

| File | Purpose |
|------|---------|
| `services/oauth/index.ts` | OAuthService class — main flow orchestration |
| `services/oauth/client.ts` | HTTP calls to Anthropic auth endpoints |
| `services/oauth/auth-code-listener.ts` | Local HTTP server for redirect capture |
| `services/oauth/crypto.ts` | PKCE code verifier/challenge generation |
| `services/oauth/getOauthProfile.ts` | Profile fetch with existing token |

## See Also

- [API Service](api-service.md) — OAuth tokens are used for API authentication headers
- [MCP Service](mcp-service.md) — MCP servers may use similar OAuth flows for their own auth
- [Analytics Service](analytics-service.md) — OAuth events (e.g., `tengu_oauth_auth_code_received`) are logged
- [Async Event Queue](../concepts/async-event-queue.md) — the listener races automatic and manual code arrivals asynchronously
- [Request Lifecycle](../syntheses/request-lifecycle.md) — authentication is a prerequisite for any API request
