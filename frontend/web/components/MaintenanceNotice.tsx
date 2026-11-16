import { Notice } from "@/components/StatusBits";
import type { MaintenanceWindow } from "@/lib/maintenance";

/** Shown instead of starting train searches or availability checks during the IRCTC window. */
export function MaintenanceNotice({ maintenance }: { maintenance: MaintenanceWindow | undefined }) {
  return (
    <Notice tone="warning" title="Railway services are paused for IRCTC maintenance">
      {maintenance?.message ??
        "Train searches and seat availability checks are temporarily unavailable."}
    </Notice>
  );
}
