import { useEffect, useState, useRef, type ReactNode } from "react";
import type { Session } from "@supabase/auth-js";
import { supabase } from "../lib/supabase";
import { useQueryClient } from "@tanstack/react-query";
import { AuthContext } from "../contexts/AuthContext";

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const accountId = useRef<string | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (accountId.current !== session?.user.id) queryClient.clear();
      accountId.current = session?.user.id ?? null;
      setSession(session);
      setLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (accountId.current !== session?.user.id) queryClient.clear();
      accountId.current = session?.user.id ?? null;
      setSession(session);
    });

    return () => subscription.unsubscribe();
  }, [queryClient]);

  const signOut = async () => {
    await supabase.auth.signOut();
  };

  return (
    <AuthContext.Provider
      value={{ session, user: session?.user ?? null, loading, signOut }}
    >
      {children}
    </AuthContext.Provider>
  );
}
