import * as sentry from "https://cdn.jsdelivr.net/npm/@sentry/browser@10.66.0/+esm";

const dsn =
  "https://1ba0c3d11d6ebd560dd356879b422f58@o4511751659651072.ingest.us.sentry.io/4511751671644160";

function stripUrlDetails(value) {
  if (!value) return value;

  try {
    const url = new URL(value, window.location.origin);
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return value;
  }
}

function removeSensitiveContext(event) {
  delete event.user;

  if (event.request?.url) {
    event.request.url = stripUrlDetails(event.request.url);
  }

  if (Array.isArray(event.breadcrumbs)) {
    event.breadcrumbs = event.breadcrumbs.map((breadcrumb) => {
      if (breadcrumb.category !== "navigation" || !breadcrumb.data) {
        return breadcrumb;
      }

      return {
        ...breadcrumb,
        data: {
          ...breadcrumb.data,
          from: stripUrlDetails(breadcrumb.data.from),
          to: stripUrlDetails(breadcrumb.data.to),
        },
      };
    });
  }

  return event;
}

sentry.init({
  dsn,
  environment:
    window.location.hostname === "tool-dun-psi.vercel.app"
      ? "production"
      : "development",
  sendDefaultPii: false,
  sampleRate: 1,
  tracesSampleRate: 0,
  maxBreadcrumbs: 50,
  beforeSend: removeSensitiveContext,
});

const testRequested =
  new URLSearchParams(window.location.search).get("sentry_test") ===
  "installation";

if (testRequested) {
  sentry.captureException(
    new Error("Alpha Lens Sentry installation verification"),
  );
}
