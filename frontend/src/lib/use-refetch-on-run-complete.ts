import { useEffect, useRef } from "react";

/** Re-fetches once a background run (DiscoveryRunProvider/PlannerRunProvider -
 * both app-root, survive navigation) completes for the assessment currently
 * being viewed - so a run that finishes while the user is sitting on a page
 * (or already finished by the time they land here) doesn't leave that page
 * stuck showing pre-run state until a manual refresh. This exact guard/effect
 * shape was previously duplicated across OverviewPage (x2, for both discovery
 * and planner runs), GraphPage, and DocumentsPage.
 *
 * `refetch` is read via a ref rather than listed as an effect dependency -
 * callers don't need to memoize it with useCallback (most don't), and putting
 * an unmemoized function in the dependency array would re-fire this effect on
 * every render instead of only on the one status transition it's meant to
 * catch. */
export function useRefetchOnRunComplete(
  runStatus: string,
  runAssessmentId: string | null,
  assessmentId: string,
  refetch: () => void,
): void {
  const refetchRef = useRef(refetch);
  refetchRef.current = refetch;

  useEffect(() => {
    if (runAssessmentId === assessmentId && runStatus === "complete") {
      refetchRef.current();
    }
  }, [runStatus, runAssessmentId, assessmentId]);
}
