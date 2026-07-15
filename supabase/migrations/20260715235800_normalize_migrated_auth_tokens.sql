-- Auth columns are historically nullable in Postgres, but current GoTrue reads
-- these token fields as strings.  Normalize migrated rows to prevent login 500s.

update auth.users
set confirmation_token = coalesce(confirmation_token, ''),
    recovery_token = coalesce(recovery_token, ''),
    email_change_token_new = coalesce(email_change_token_new, ''),
    email_change = coalesce(email_change, ''),
    phone_change = coalesce(phone_change, ''),
    phone_change_token = coalesce(phone_change_token, ''),
    email_change_token_current = coalesce(email_change_token_current, ''),
    reauthentication_token = coalesce(reauthentication_token, ''),
    email_change_confirm_status = coalesce(email_change_confirm_status, 0),
    is_sso_user = coalesce(is_sso_user, false),
    is_anonymous = coalesce(is_anonymous, false)
where confirmation_token is null
   or recovery_token is null
   or email_change_token_new is null
   or email_change is null
   or phone_change is null
   or phone_change_token is null
   or email_change_token_current is null
   or reauthentication_token is null
   or email_change_confirm_status is null
   or is_sso_user is null
   or is_anonymous is null;
