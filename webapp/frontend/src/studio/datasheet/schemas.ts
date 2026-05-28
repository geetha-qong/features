export type FieldWidth = "xs" | "sm" | "md" | "full";

export interface FieldDef {
  key: string;
  label: string;
  w: FieldWidth;
  extracted?: boolean;
  conf?: number;
}

export interface SectionDef {
  title: string;
  fields: FieldDef[];
}

export interface DocType {
  key: DocTypeKey;
  name: string;
  icon: string;
  /** True for the 4 deliverables locked in for Phase 1 of the agency MVP.
   *  Rendered first and visually highlighted. */
  phase1?: boolean;
}

export type DocTypeKey =
  | "index"
  | "datasheet"
  | "valves"
  | "io"
  | "narrative"
  | "cande"
  | "lines"
  | "equip"
  | "loop"
  | "tags";

// Phase 1 deliverables first (highlighted as primary). The remaining six are
// secondary — still selectable, but visually de-emphasized.
export const DOC_TYPES: DocType[] = [
  { key: "index", name: "Instrument Index", icon: "list-checks", phase1: true },
  { key: "datasheet", name: "Instrument Datasheet", icon: "file-text", phase1: true },
  { key: "valves", name: "Valve List", icon: "git-pull-request", phase1: true },
  { key: "io", name: "I/O List", icon: "list", phase1: true },
  { key: "narrative", name: "Control Narrative", icon: "scroll-text" },
  { key: "cande", name: "Cause & Effect", icon: "git-merge" },
  { key: "lines", name: "Line List", icon: "git-branch" },
  { key: "equip", name: "Equipment List", icon: "boxes" },
  { key: "loop", name: "Loop Schedule", icon: "repeat" },
  { key: "tags", name: "Tag Register", icon: "tag" },
];

export const SCHEMAS: Record<DocTypeKey, SectionDef[]> = {
  datasheet: [
    {
      title: "Identification",
      fields: [
        { key: "tag", label: "Tag No", w: "xs", extracted: true, conf: 0.97 },
        { key: "loopNo", label: "Loop #", w: "xs", extracted: true, conf: 0.88 },
        { key: "instType", label: "Inst Type", w: "sm", extracted: true, conf: 0.93 },
        { key: "service", label: "Service", w: "md", extracted: true, conf: 0.74 },
        { key: "instDesc", label: "Description", w: "full", extracted: true, conf: 0.81 },
      ],
    },
    {
      title: "P&ID Reference",
      fields: [
        { key: "pid", label: "P&ID", w: "sm", extracted: true, conf: 0.99 },
        { key: "pidRev", label: "Rev", w: "xs", extracted: true, conf: 0.99 },
        { key: "lineNo", label: "Line No", w: "sm", extracted: true, conf: 0.86 },
        { key: "lineSize", label: "Size", w: "xs", extracted: true, conf: 0.91 },
        { key: "equipNo", label: "Equip No", w: "xs", extracted: true, conf: 0.69 },
        { key: "unitNo", label: "Unit No", w: "xs", extracted: false },
      ],
    },
    {
      title: "Signal & I/O",
      fields: [
        { key: "signal", label: "Signal", w: "sm", extracted: true, conf: 0.95 },
        { key: "ioType", label: "I/O Type", w: "xs", extracted: true, conf: 0.92 },
        { key: "ioCp", label: "I/O C+P", w: "xs", extracted: false },
        { key: "ioLoc", label: "I/O Location", w: "sm", extracted: false },
      ],
    },
    {
      title: "Mechanical",
      fields: [
        { key: "valveType", label: "Valve Type", w: "sm", extracted: true, conf: 0.84 },
        { key: "stemLoc", label: "Stem", w: "xs", extracted: true, conf: 0.66 },
        { key: "bodyMat", label: "Body Mat", w: "xs", extracted: false },
        { key: "inletRating", label: "Inlet Rating", w: "xs", extracted: false },
        { key: "outletRating", label: "Outlet Rating", w: "xs", extracted: false },
        { key: "handwheel", label: "Handwheel", w: "xs", extracted: false },
      ],
    },
  ],

  // Instrument Index schema mirrors the column structure of a real RCC
  // INST INDEX deliverable (57-col XLSX, e.g. C15-40-SCJV-MJ-5000103187-001).
  // Grouped into 11 accordion sections so the drawer stays scannable;
  // every column from the customer's index ends up here.
  index: [
    {
      title: "Identification",
      fields: [
        { key: "sNo", label: "S.No", w: "xs", extracted: true, conf: 0.99 },
        { key: "itemNo", label: "Item No", w: "sm", extracted: true, conf: 0.92 },
        { key: "tag", label: "Tag No", w: "xs", extracted: true, conf: 0.97 },
        { key: "vpRevNo", label: "VP Rev", w: "xs", extracted: false },
        { key: "reqNo", label: "Req No", w: "sm", extracted: true, conf: 0.86 },
      ],
    },
    {
      title: "Process & Location",
      fields: [
        { key: "unitNo", label: "Unit No", w: "xs", extracted: true, conf: 0.95 },
        { key: "service", label: "Service", w: "md", extracted: true, conf: 0.74 },
        { key: "loopNo", label: "Loop No", w: "sm", extracted: true, conf: 0.88 },
        { key: "pid", label: "P&ID No", w: "sm", extracted: true, conf: 0.99 },
        { key: "processFunction", label: "Process Function", w: "sm", extracted: true, conf: 0.81 },
        { key: "lineNo", label: "Line No", w: "sm", extracted: true, conf: 0.86 },
        { key: "pipingClass", label: "Piping Class", w: "xs", extracted: true, conf: 0.78 },
        { key: "locationName", label: "Location", w: "sm", extracted: false },
      ],
    },
    {
      title: "Type Classification",
      fields: [
        { key: "instType", label: "Inst Type", w: "xs", extracted: true, conf: 0.93 },
        { key: "instTypeDesc", label: "Inst Type Description", w: "md", extracted: true, conf: 0.86 },
        { key: "instType2", label: "Inst Type 2", w: "xs", extracted: true, conf: 0.84 },
        { key: "type2Desc", label: "Type 2 Description", w: "md", extracted: true, conf: 0.78 },
      ],
    },
    {
      title: "I/O & Signal",
      fields: [
        { key: "ioType", label: "I/O Type", w: "xs", extracted: true, conf: 0.92 },
        { key: "subIoType", label: "Sub I/O Type", w: "xs", extracted: false },
        { key: "signalType", label: "Signal Type", w: "sm", extracted: true, conf: 0.9 },
        { key: "system", label: "System", w: "xs", extracted: false },
        { key: "subSystem", label: "Sub-System", w: "xs", extracted: false },
        { key: "ioLocation", label: "I/O Location", w: "sm", extracted: false },
      ],
    },
    {
      title: "Hardware",
      fields: [
        { key: "isType", label: "IS Type", w: "xs", extracted: false },
        { key: "make", label: "Make", w: "sm", extracted: false },
        { key: "model", label: "Model", w: "sm", extracted: false },
        { key: "externalPower", label: "External Power", w: "xs", extracted: false },
      ],
    },
    {
      title: "Calibration Range",
      fields: [
        { key: "calbRangeMin", label: "Calib Min", w: "xs", extracted: false },
        { key: "calbRangeMax", label: "Calib Max", w: "xs", extracted: false },
        { key: "calbRangeUnit", label: "Unit", w: "xs", extracted: false },
      ],
    },
    {
      title: "Measuring Range",
      fields: [
        { key: "measuringRangeMin", label: "Measuring Min", w: "xs", extracted: false },
        { key: "measuringRangeMax", label: "Measuring Max", w: "xs", extracted: false },
        { key: "measuringRangeUnit", label: "Unit", w: "xs", extracted: false },
      ],
    },
    {
      title: "Alarms & Trips",
      fields: [
        { key: "alarmHHH", label: "Alarm HHH", w: "xs", extracted: false },
        { key: "alarmHH", label: "Alarm HH", w: "xs", extracted: false },
        { key: "alarmH", label: "Alarm H", w: "xs", extracted: false },
        { key: "alarmL", label: "Alarm L", w: "xs", extracted: false },
        { key: "alarmLL", label: "Alarm LL", w: "xs", extracted: false },
        { key: "alarmLLL", label: "Alarm LLL", w: "xs", extracted: false },
        { key: "tripMultiply", label: "Trip Multiply", w: "xs", extracted: false },
      ],
    },
    {
      title: "Scope of Supply",
      fields: [
        { key: "scopeOfSupply", label: "Scope of Supply", w: "sm", extracted: false },
        { key: "scopeOfWiring", label: "Scope of Wiring", w: "sm", extracted: false },
        { key: "scopeOfInstall", label: "Scope of Install", w: "sm", extracted: false },
        { key: "scopeOfAirConn", label: "Scope of Air Conn", w: "sm", extracted: false },
        { key: "tracing", label: "Tracing", w: "xs", extracted: false },
        { key: "externalPowerSow", label: "External Power SOW", w: "sm", extracted: false },
        { key: "pidControlAction", label: "PID Control Action", w: "sm", extracted: false },
      ],
    },
    {
      title: "Status & Failure",
      fields: [
        { key: "status0", label: "Status 0", w: "xs", extracted: false },
        { key: "status1", label: "Status 1", w: "xs", extracted: false },
        { key: "failureAction", label: "Failure Action", w: "sm", extracted: false },
      ],
    },
    {
      title: "Documentation",
      fields: [
        { key: "calReportRequirement", label: "Cal Report Reqd?", w: "xs", extracted: false },
        { key: "calReportDocNo", label: "Cal Report Doc No", w: "sm", extracted: false },
        { key: "calReportSubmit", label: "Cal Report Submit", w: "sm", extracted: false },
        { key: "silCertiRequirement", label: "SIL Certi Reqd?", w: "xs", extracted: false },
        { key: "silCertiSubmit", label: "SIL Certi Submit", w: "sm", extracted: false },
        { key: "remarks", label: "Remarks", w: "full", extracted: false },
      ],
    },
  ],

  narrative: [
    {
      title: "Loop",
      fields: [
        { key: "tag", label: "Primary Tag", w: "xs", extracted: true, conf: 0.97 },
        { key: "loopNo", label: "Loop #", w: "xs", extracted: true, conf: 0.88 },
        { key: "loopType", label: "Loop Type", w: "sm", extracted: true, conf: 0.83 },
        { key: "service", label: "Service", w: "md", extracted: true, conf: 0.74 },
      ],
    },
    {
      title: "Control Logic",
      fields: [
        { key: "setpoint", label: "Setpoint", w: "xs", extracted: false },
        { key: "range", label: "Range", w: "sm", extracted: true, conf: 0.71 },
        { key: "action", label: "Action", w: "xs", extracted: true, conf: 0.78 },
        { key: "failPos", label: "Fail Position", w: "xs", extracted: true, conf: 0.66 },
        { key: "narrative", label: "Narrative Text", w: "full", extracted: false },
      ],
    },
    {
      title: "Alarms & Interlocks",
      fields: [
        { key: "hh", label: "HH Trip", w: "xs", extracted: false },
        { key: "h", label: "H Alarm", w: "xs", extracted: false },
        { key: "l", label: "L Alarm", w: "xs", extracted: false },
        { key: "ll", label: "LL Trip", w: "xs", extracted: false },
      ],
    },
  ],

  cande: [
    {
      title: "Cause",
      fields: [
        { key: "causeTag", label: "Cause Tag", w: "xs", extracted: true, conf: 0.91 },
        { key: "causeType", label: "Cause Type", w: "sm", extracted: true, conf: 0.85 },
        { key: "causeSP", label: "Trip Setpoint", w: "xs", extracted: true, conf: 0.74 },
        { key: "causeDesc", label: "Description", w: "full", extracted: true, conf: 0.79 },
      ],
    },
    {
      title: "Effects",
      fields: [
        { key: "effect1", label: "Effect 1", w: "sm", extracted: true, conf: 0.88 },
        { key: "effect2", label: "Effect 2", w: "sm", extracted: true, conf: 0.81 },
        { key: "effect3", label: "Effect 3", w: "sm", extracted: false },
        { key: "logic", label: "Logic", w: "xs", extracted: true, conf: 0.69 },
        { key: "delay", label: "Delay (s)", w: "xs", extracted: false },
        { key: "bypass", label: "Bypassable", w: "xs", extracted: false },
      ],
    },
  ],

  io: [
    {
      title: "Signal",
      fields: [
        { key: "tag", label: "Tag No", w: "xs", extracted: true, conf: 0.97 },
        { key: "ioType", label: "I/O Type", w: "xs", extracted: true, conf: 0.92 },
        { key: "signal", label: "Signal", w: "sm", extracted: true, conf: 0.95 },
        { key: "service", label: "Service", w: "md", extracted: true, conf: 0.74 },
      ],
    },
    {
      title: "DCS Address",
      fields: [
        { key: "ioCard", label: "Card", w: "xs", extracted: false },
        { key: "ioSlot", label: "Slot", w: "xs", extracted: false },
        { key: "ioChannel", label: "Channel", w: "xs", extracted: false },
        { key: "ioAddr", label: "Address", w: "sm", extracted: false },
      ],
    },
    {
      title: "Engineering",
      fields: [
        { key: "range", label: "Range", w: "sm", extracted: true, conf: 0.71 },
        { key: "units", label: "Units", w: "xs", extracted: true, conf: 0.94 },
        { key: "rangeLow", label: "Range Low", w: "xs", extracted: false },
        { key: "rangeHigh", label: "Range High", w: "xs", extracted: false },
      ],
    },
  ],

  valves: [
    {
      title: "Identification",
      fields: [
        { key: "tag", label: "Tag No", w: "xs", extracted: true, conf: 0.97 },
        { key: "valveType", label: "Valve Type", w: "sm", extracted: true, conf: 0.84 },
        { key: "size", label: "Size", w: "xs", extracted: true, conf: 0.91 },
        { key: "service", label: "Service", w: "md", extracted: true, conf: 0.74 },
      ],
    },
    {
      title: "Construction",
      fields: [
        { key: "body", label: "Body", w: "xs", extracted: false },
        { key: "trim", label: "Trim", w: "xs", extracted: false },
        { key: "seat", label: "Seat", w: "xs", extracted: false },
        { key: "stem", label: "Stem", w: "xs", extracted: true, conf: 0.66 },
        { key: "rating", label: "Rating", w: "xs", extracted: true, conf: 0.77 },
      ],
    },
    {
      title: "Performance",
      fields: [
        { key: "cv", label: "Cv", w: "xs", extracted: false },
        { key: "action", label: "Action", w: "xs", extracted: true, conf: 0.78 },
        { key: "failPos", label: "Fail Pos", w: "xs", extracted: true, conf: 0.66 },
        { key: "actuator", label: "Actuator", w: "sm", extracted: false },
      ],
    },
  ],

  lines: [
    {
      title: "Line",
      fields: [
        { key: "lineNo", label: "Line No", w: "sm", extracted: true, conf: 0.86 },
        { key: "size", label: "Size", w: "xs", extracted: true, conf: 0.91 },
        { key: "sched", label: "Sched", w: "xs", extracted: false },
        { key: "service", label: "Service", w: "md", extracted: true, conf: 0.74 },
      ],
    },
    {
      title: "Material & Spec",
      fields: [
        { key: "material", label: "Material", w: "sm", extracted: false },
        { key: "spec", label: "Piping Spec", w: "xs", extracted: false },
        { key: "rating", label: "Rating", w: "xs", extracted: true, conf: 0.77 },
        { key: "insul", label: "Insulation", w: "xs", extracted: false },
        { key: "tracing", label: "Tracing", w: "xs", extracted: false },
      ],
    },
  ],

  equip: [
    {
      title: "Equipment",
      fields: [
        { key: "equipNo", label: "Equipment No", w: "xs", extracted: true, conf: 0.69 },
        { key: "equipType", label: "Type", w: "sm", extracted: true, conf: 0.92 },
        { key: "service", label: "Service", w: "md", extracted: true, conf: 0.74 },
      ],
    },
    {
      title: "Design",
      fields: [
        { key: "dPress", label: "Design Press", w: "xs", extracted: false },
        { key: "dTemp", label: "Design Temp", w: "xs", extracted: false },
        { key: "matl", label: "Material", w: "sm", extracted: false },
        { key: "weight", label: "Weight", w: "xs", extracted: false },
      ],
    },
  ],

  loop: [
    {
      title: "Loop",
      fields: [
        { key: "loopNo", label: "Loop #", w: "xs", extracted: true, conf: 0.88 },
        { key: "loopType", label: "Loop Type", w: "sm", extracted: true, conf: 0.83 },
        { key: "service", label: "Service", w: "md", extracted: true, conf: 0.74 },
        { key: "pid", label: "P&ID", w: "sm", extracted: true, conf: 0.99 },
        { key: "sheet", label: "Sheet", w: "xs", extracted: true, conf: 0.97 },
        { key: "function", label: "Function", w: "sm", extracted: false },
      ],
    },
  ],

  tags: [
    {
      title: "Tag",
      fields: [
        { key: "tag", label: "Tag No", w: "xs", extracted: true, conf: 0.97 },
        { key: "instType", label: "Type", w: "sm", extracted: true, conf: 0.93 },
        { key: "disc", label: "Discipline", w: "xs", extracted: true, conf: 0.9 },
        { key: "pid", label: "P&ID", w: "sm", extracted: true, conf: 0.99 },
        { key: "instDesc", label: "Description", w: "full", extracted: true, conf: 0.81 },
      ],
    },
  ],
};

export function defaultValues(elementId: string, type: string, _docType: DocTypeKey): Record<string, string> {
  const isPV = elementId === "PV-203";
  const isFT = elementId === "FT-101";
  return {
    tag: elementId,
    pid: "CDU-PID-001",
    pidRev: "R3",
    instType: type,
    disc: type && type.toLowerCase().includes("valve") ? "Mech" : "Inst",
    instDesc:
      type === "Control Valve"
        ? "Globe, Pneumatic Actuator, Air-to-open"
        : type === "Flow Transmitter"
          ? "Differential Pressure, 4-20mA HART"
          : type === "Block Valve"
            ? "Gate valve, lever operated"
            : "",
    service:
      type === "Control Valve"
        ? "Crude → E-104 inlet"
        : type === "Flow Transmitter"
          ? "Reflux header flow"
          : "Crude charge",
    loopNo: isPV ? "FIC-203" : isFT ? "FIC-101" : "FIC-100",
    lineNo: isPV ? "P-12-101-CS150" : "P-12-102-CS150",
    equipNo: "E-104",
    lineSize: '4"',
    size: '4"',
    rating: "ANSI 150",
    signal: "4-20mA HART",
    ioType: type && type.includes("Valve") ? "AO" : "AI",
    units: "kg/h",
    range: type === "Flow Transmitter" ? "0 – 25 000 kg/h" : "0 – 600 kPa",
    rangeLow: "0",
    rangeHigh: type === "Flow Transmitter" ? "25000" : "600",
    stem: "Vertical",
    stemLoc: "Vertical",
    valveType: type === "Control Valve" ? "Globe, Single-Seat" : type === "Block Valve" ? "Gate" : "",
    action: "Air-to-open",
    failPos: "Fail Closed",
    loopType: "Flow Control",
    setpoint: "18 200",
    causeTag: isPV ? "PT-201" : "FT-101",
    causeType: "High Pressure",
    causeSP: "650 kPa",
    causeDesc: "Crude inlet pressure exceeds vessel design",
    effect1: "Close PV-203",
    effect2: "Trip P-101",
    logic: "2oo3",
    sheet: "04",
    function: "Flow Control",
  };
}
