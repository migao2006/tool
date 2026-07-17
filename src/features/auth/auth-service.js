export function createAuthService(client, redirectUrl) {
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
        options: { emailRedirectTo: redirectUrl.replace("?auth=recovery", "") },
      });
    },

    sendOtp(email) {
      return client.auth.signInWithOtp({
        email,
        options: { shouldCreateUser: true },
      });
    },

    verifyOtp(email, token) {
      return client.auth.verifyOtp({ email, token, type: "email" });
    },

    sendPasswordReset(email) {
      return client.auth.resetPasswordForEmail(email, { redirectTo: redirectUrl });
    },

    updatePassword(password) {
      return client.auth.updateUser({ password });
    },

    signOut() {
      return client.auth.signOut({ scope: "local" });
    },
  };
}
