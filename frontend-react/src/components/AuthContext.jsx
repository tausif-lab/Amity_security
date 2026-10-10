import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { supabase } from "../../lib/supabase";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [role, setRole] = useState(null);
  const [loading, setLoading] = useState(true);

  // Role lives in the `profiles` table (set by a DB trigger), not in browser-editable metadata.
  const loadRole = useCallback(async (userId) => {
    const { data } = await supabase
      .from("profiles")
      .select("role")
      .eq("id", userId)
      .single();
    setRole(data?.role ?? null);
  }, []);

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data }) => {
      setSession(data.session);
      if (data.session) await loadRole(data.session.user.id);
      setLoading(false);
    });

    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      setSession(s);
      // defer to avoid calling Supabase inside its own auth callback
      if (s) setTimeout(() => loadRole(s.user.id), 0);
      else setRole(null);
    });
    return () => sub.subscription.unsubscribe();
  }, [loadRole]);

  const signUp = (email, password, chosenRole) =>
    supabase.auth.signUp({
      email,
      password,
      options: { data: { role: chosenRole } },
    });

  const signIn = (email, password) =>
    supabase.auth.signInWithPassword({ email, password });

  const signOut = () => supabase.auth.signOut();

  return (
    <AuthContext.Provider
      value={{ session, user: session?.user ?? null, role, loading, signUp, signIn, signOut }}
    >
      {children}
    </AuthContext.Provider>
  );
}