/**
 * Session-lifetime cache around an async loader: concurrent callers share one
 * in-flight request, a success is kept for the rest of the session, failures
 * are never cached. `load({ force: true })` refetches.
 *
 * The loader receives no abort signal on purpose: one consumer unmounting must
 * not cancel a request other consumers are waiting for.
 */
export function createSessionCache(loader) {
  let value;
  let hasValue = false;
  let inflight = null;

  return {
    peek: () => (hasValue ? value : undefined),
    has: () => hasValue,
    load({ force = false } = {}) {
      if (hasValue && !force) return Promise.resolve(value);
      if (inflight) return inflight;
      const request = Promise.resolve()
        .then(() => loader())
        .then(
          (result) => {
            if (inflight === request) inflight = null;
            value = result;
            hasValue = true;
            return result;
          },
          (error) => {
            if (inflight === request) inflight = null;
            throw error;
          },
        );
      inflight = request;
      return request;
    },
    reset() {
      value = undefined;
      hasValue = false;
      inflight = null;
    },
  };
}
