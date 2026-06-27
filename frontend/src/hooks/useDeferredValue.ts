/**Stable wrapper around useDeferredValue for older React + convenient typing.*/

import { useDeferredValue as useReactDeferredValue, useMemo } from "react";

/**
 * Returns a deferred version of `value` that lags behind during rapid
 * updates. Use to keep heavy filter work from blocking typing.
 */
export function useDeferredValue<T>(value: T): T {
  return useReactDeferredValue(value);
}
