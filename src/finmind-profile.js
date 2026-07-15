const profile = ({
  id,
  authenticated,
  hourlyLimit,
  companyBatchLimit,
  etfBatchLimit,
  companyClaimCap,
  etfClaimCap,
}) => Object.freeze({
  id,
  authenticated,
  hourlyLimit,
  companyBatchLimit,
  etfBatchLimit,
  companyClaimCap,
  etfClaimCap,
  // The three deep groups run three times per hour.  This is the maximum
  // demand before the shared rolling-hour ledger trims a reservation.
  scheduledClaimPerHour: 3 * ((2 * companyClaimCap) + etfClaimCap),
});

export const FINMIND_PROFILES = Object.freeze({
  public: profile({
    id: "public-300",
    authenticated: false,
    hourlyLimit: 300,
    companyBatchLimit: 10,
    etfBatchLimit: 19,
    companyClaimCap: 50,
    etfClaimCap: 19,
  }),
  authenticated: profile({
    id: "authenticated-600",
    authenticated: true,
    hourlyLimit: 600,
    companyBatchLimit: 22,
    etfBatchLimit: 23,
    companyClaimCap: 88,
    etfClaimCap: 23,
  }),
});

export function selectFinmindProfile(token) {
  return String(token || "").trim()
    ? FINMIND_PROFILES.authenticated
    : FINMIND_PROFILES.public;
}
