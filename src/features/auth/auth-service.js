function sameOriginRedirect(value, fieldName) {
  const target = new URL(value, globalThis.location?.href);
  if (globalThis.location?.origin && target.origin !== globalThis.location.origin) {
    throw new Error(`${fieldName} must use the current application origin`);
  }
  return target.toString();
}

export function createAuthService(
  client,
  confirmationRedirectUrl,
  passwordRecoveryRedirectUrl = confirmationRedirectUrl,
) {
  const confirmationRedirect = sameOriginRedirect(
    confirmationRedirectUrl,
    "confirmation redirect",
  );
  const recoveryRedirect = sameOriginRedirect(
    passwordRecoveryRedirectUrl,
    "password recovery redirect",
  );

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
        options: { emailRedirectTo: confirmationRedirect },
      });
    },

    resetPasswordForEmail(email) {
      return client.auth.resetPasswordForEmail(email, {
        redirectTo: recoveryRedirect,
      });
    },

    updatePassword(password) {
      return client.auth.updateUser({ password });
    },

    signOut() {
      return client.auth.signOut({ scope: "local" });
    },
  };
}
