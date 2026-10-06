// Offline stand-in for the Supabase client: a signed-in demo session, no network.
const user = { id: "u-demo", email: "demo@kioku.dev", aud: "authenticated", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" };
const session = { access_token: "demo", refresh_token: "demo", expires_at: 4102444800, expires_in: 3600, token_type: "bearer", user };
let signedIn = true;
export const supabase = {
  auth: {
    getSession: async () => ({ data: { session: signedIn ? session : null }, error: null }),
    onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    signOut: async () => ({ error: null }),
    signInWithPassword: async () => new Promise((r) => setTimeout(() => r({ data: { session, user }, error: null }), 600)),
    signUp: async () => new Promise((r) => setTimeout(() => r({ data: { session, user }, error: null }), 600)),
  },
};
export function __setSignedIn(v: boolean) { signedIn = v; }
