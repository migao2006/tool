(function configureSentryMonitoring(global) {
  "use strict";

  const sentry = global.Sentry;
  if (!sentry || typeof sentry.init !== "function") return;

  const dsn =
    "https://1ba0c3d11d6ebd560dd356879b422f58@o4511751659651072.ingest.us.sentry.io/4511751671644160";

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

  sentry.init({
    dsn,
    environment: /^(?:localhost|127\.0\.0\.1)$/u.test(global.location.hostname)
      ? "development"
      : "production",
    sendDefaultPii: false,
    sampleRate: 1,
    tracesSampleRate: 0,
    maxBreadcrumbs: 50,
    beforeSend: removeSensitiveContext,
  });

})(window);
