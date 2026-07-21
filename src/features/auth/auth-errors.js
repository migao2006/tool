export function friendlyAuthError(error) {
  const code = error?.code ?? "";
  const message = error?.message ?? "";
  if (/password mismatch/i.test(message)) return "兩次輸入的密碼不一致。";
  if (/recovery session missing/i.test(message)) {
    return "密碼重設連結已失效，請重新申請。";
  }
  if (code === "email_not_confirmed" || /email not confirmed/i.test(message)) {
    return "Email 尚未完成確認，請先開啟確認信中的連結。";
  }
  if (code === "invalid_credentials" || /invalid login credentials/i.test(message)) {
    return "Email 或密碼不正確。";
  }
  if (code === "over_request_rate_limit" || /rate limit/i.test(message)) {
    return "操作太頻繁，請稍後再試。";
  }
  if (/already registered/i.test(message)) return "此 Email 已建立帳號。";
  if (
    code === "otp_expired" ||
    code === "flow_state_expired" ||
    /expired|invalid.*(?:token|code)|otp.*expired/i.test(message)
  ) {
    return "密碼重設連結已失效，請重新申請。";
  }
  if (code === "same_password" || /same password/i.test(message)) {
    return "新密碼不可與目前密碼相同。";
  }
  if (code === "weak_password" || /password/i.test(message)) {
    return "密碼需至少 8 個字元，並符合系統安全要求。";
  }
  return "目前無法完成操作，請稍後再試。";
}
