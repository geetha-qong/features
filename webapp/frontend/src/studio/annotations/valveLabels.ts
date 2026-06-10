/**
 * Local copy of the valve sub_class label map. buildElements.ts keeps its own
 * private VALVE_SUB_CLASS_LABELS const that isn't exported; rather than mutate
 * a file outside this phase's scope, the same table is mirrored here. If the
 * two ever drift, fix buildElements.ts to export the map and import it here.
 */
export const VALVE_SUB_CLASS_LABELS: Record<string, string> = {
  BV: "Ball Valve",
  BF: "Butterfly Valve",
  GT: "Gate Valve",
  CK: "Check Valve",
  DB: "Double Block",
  GL: "Globe Valve",
  CV: "Control Valve",
  NCBV: "NC Ball Valve",
  VB: "Block Valve",
  VF: "Flow Valve",
  VD: "Drain Valve",
  PV: "Pressure Valve",
  SB: "Sample/Bleed Valve",
};
