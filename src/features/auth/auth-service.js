export function createAuthService(client, confirmationRedirectUrl) {
  return {
    getSession() {
      return client.auth.getSession();
    },

    onAuthStateChange(callback) {
      const { data } = client.auth.onAuthStateChange(callback);
      return () => data.subscription.unsubscribe();
    },

    signInWithPassword(email, password) {
      return client.auth.signInWithPassword({ email, password });
    },

    signUp(email, password) {
      return client.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: confirmationRedirectUrl },
      });
    },

    signOut() {
      return client.auth.signOut({ scope: "local" });
    },
  };
}
