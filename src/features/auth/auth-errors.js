export function friendlyAuthError(error) {
  const message = error?.message ?? "";
  if (/password mismatch/i.test(message)) return "兩次輸入的密碼不一致。";
  if (/invalid login credentials/i.test(message)) return "Email 或密碼不正確。";
  if (/rate limit/i.test(message)) return "操作太頻繁，請稍後再試。";
  if (/already registered/i.test(message)) return "此 Email 已建立帳號。";
  if (/expired|invalid.*token/i.test(message)) return "驗證碼已失效，請重新寄送。";
  if (/password/i.test(message)) return "密碼需至少 8 個字元。";
  return "目前無法完成操作，請稍後再試。";
}
