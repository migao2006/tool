(function configureSentryMonitoring(global) {
  "use strict";

  const sentry = global.Sentry;
  if (!sentry || typeof sentry.onLoad !== "function") return;

  function stripUrlDetails(value) {
    if (!value) return value;

    try {
      const url = new URL(value, global.location.origin);
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

  sentry.onLoad(function initializeSentry() {
    sentry.init({
      environment:
        global.location.hostname === "tool-dun-psi.vercel.app"
          ? "production"
          : "development",
      sendDefaultPii: false,
      sampleRate: 1,
      tracesSampleRate: 0,
      maxBreadcrumbs: 50,
      beforeSend: removeSensitiveContext,
    });

    const testRequested =
      new URLSearchParams(global.location.search).get("sentry_test") ===
      "installation";

    if (testRequested) {
      sentry.captureException(
        new Error("Alpha Lens Sentry installation verification"),
      );
    }
  });
})(window);
