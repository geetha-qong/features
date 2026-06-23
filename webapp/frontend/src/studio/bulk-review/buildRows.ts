import type { ProjectLike } from "../types";

export interface BulkRow {
  id: string;
  tag: string;
  type: string;
  valveType: string;
  body: string;
  cv: string;
  action: string;
  failPos: string;
  loop: string;
  loopType: string;
  io: string;
  signal: string;
  card: string;
  slot: string;
  channel: string;
  addr: string;
  range: string;
  setpoint: string;
  st: number;
  sel?: boolean;
  missing?: boolean;
  pid: string;
  line: string;
  size: string;
  sched: string;
  material: string;
  rating: string;
  insul: string;
  disc: string;
  service: string;
  loc: string;
  dPress: string;
  dTemp: string;
  equipNo: string;
  equipType: string;
  sheet: string;
  func: string;
  description: string;
  causeTag: string;
  causeType: string;
  tripSP: string;
  effect1: string;
  effect2: string;
  logic: string;
  bypass: string;
  actuator: string;
  [key: string]: string | number | boolean | undefined;
}

interface BaseRow {
  id: string;
  tag: string;
  type: string;
  valveType: string;
  body: string;
  cv: string;
  action: string;
  failPos: string;
  loop: string;
  loopType: string;
  io: string;
  signal: string;
  card: string;
  slot: string;
  channel: string;
  addr: string;
  range: string;
  setpoint: string;
  st: number;
  sel?: boolean;
  missing?: boolean;
}

const BASE: BaseRow[] = [
  { id: "PV-203",  tag: "PV-203", type: "Control Valve",       valveType: "Globe, Single-Seat", body: "WCC",  cv: "86",  action: "Air-to-open",  failPos: "FC", loop: "FIC-203", loopType: "Flow Control",  io: "AO", signal: "4-20mA",      card: "AO-01", slot: "03", channel: "07", addr: "10.0.3.7",  range: "0 – 25 000 kg/h", setpoint: "18 200", st: 37,  sel: true },
  { id: "FT-101",  tag: "FT-101", type: "Flow Transmitter",    valveType: "—",                  body: "—",    cv: "—",   action: "—",            failPos: "—",  loop: "FIC-101", loopType: "Flow Control",  io: "AI", signal: "4-20mA HART", card: "AI-01", slot: "01", channel: "02", addr: "10.0.1.2",  range: "0 – 25 000 kg/h", setpoint: "16 400", st: 88 },
  { id: "V-101",   tag: "V-101",  type: "Block Valve",         valveType: "Gate",               body: "WCB",  cv: "—",   action: "Hand",         failPos: "—",  loop: "—",       loopType: "—",             io: "—",  signal: "—",           card: "—",     slot: "—",  channel: "—",  addr: "—",         range: "—",                setpoint: "—",      st: 100 },
  { id: "PT-201",  tag: "PT-201", type: "Press Transmitter",   valveType: "—",                  body: "—",    cv: "—",   action: "—",            failPos: "—",  loop: "PIC-201", loopType: "Press Control", io: "AI", signal: "4-20mA HART", card: "AI-01", slot: "02", channel: "05", addr: "10.0.2.5",  range: "0 – 1000 kPa",     setpoint: "650",    st: 62 },
  { id: "TT-301",  tag: "TT-301", type: "Temp Transmitter",    valveType: "—",                  body: "—",    cv: "—",   action: "—",            failPos: "—",  loop: "TIC-301", loopType: "Temp Control",  io: "AI", signal: "4-20mA HART", card: "AI-02", slot: "01", channel: "03", addr: "10.0.4.3",  range: "0 – 400 °C",       setpoint: "265",    st: 44 },
  { id: "LT-401",  tag: "LT-401", type: "Level Transmitter",   valveType: "—",                  body: "—",    cv: "—",   action: "—",            failPos: "—",  loop: "LIC-401", loopType: "Level Control", io: "AI", signal: "4-20mA HART", card: "AI-02", slot: "02", channel: "01", addr: "10.0.4.1",  range: "0 – 100 %",        setpoint: "55",     st: 76,  missing: true },
  { id: "FV-101",  tag: "FV-101", type: "Control Valve",       valveType: "Globe, Cage-Guided", body: "WCC",  cv: "62",  action: "Air-to-close", failPos: "FO", loop: "FIC-101", loopType: "Flow Control",  io: "AO", signal: "4-20mA",      card: "AO-01", slot: "01", channel: "04", addr: "10.0.3.4",  range: "0 – 18 000 kg/h",  setpoint: "12 400", st: 29 },
  { id: "PSV-022", tag: "PSV-022",type: "Relief Valve",        valveType: "Spring-Loaded",      body: "316SS",cv: "—",   action: "Self-acting",  failPos: "—",  loop: "—",       loopType: "—",             io: "—",  signal: "—",           card: "—",     slot: "—",  channel: "—",  addr: "—",         range: "—",                setpoint: "1200 kPa", st: 100 },
  { id: "XV-501",  tag: "XV-501", type: "ESD Valve",           valveType: "Ball, Trunnion",     body: "A105", cv: "—",   action: "On/Off",       failPos: "FC", loop: "ESD-501", loopType: "Safety",        io: "DO", signal: "24VDC",       card: "DO-01", slot: "02", channel: "06", addr: "10.0.5.6",  range: "Open / Closed",    setpoint: "—",      st: 55 },
  { id: "P-101",   tag: "P-101",  type: "Centrifugal Pump",    valveType: "—",                  body: "—",    cv: "—",   action: "—",            failPos: "—",  loop: "—",       loopType: "—",             io: "—",  signal: "—",           card: "—",     slot: "—",  channel: "—",  addr: "—",         range: "—",                setpoint: "—",      st: 92 },
  { id: "E-104",   tag: "E-104",  type: "Shell & Tube Exch.",  valveType: "—",                  body: "—",    cv: "—",   action: "—",            failPos: "—",  loop: "—",       loopType: "—",             io: "—",  signal: "—",           card: "—",     slot: "—",  channel: "—",  addr: "—",         range: "—",                setpoint: "—",      st: 18,  missing: true },
  { id: "FT-202",  tag: "FT-202", type: "Flow Transmitter",    valveType: "—",                  body: "—",    cv: "—",   action: "—",            failPos: "—",  loop: "FIC-202", loopType: "Flow Control",  io: "AI", signal: "4-20mA HART", card: "AI-01", slot: "03", channel: "01", addr: "10.0.1.3",  range: "0 – 12 000 kg/h",  setpoint: "8 800",  st: 71 },
  { id: "PT-301",  tag: "PT-301", type: "Press Transmitter",   valveType: "—",                  body: "—",    cv: "—",   action: "—",            failPos: "—",  loop: "PIC-301", loopType: "Press Control", io: "AI", signal: "4-20mA HART", card: "AI-02", slot: "03", channel: "02", addr: "10.0.4.2",  range: "0 – 1600 kPa",     setpoint: "950",    st: 0,   missing: true },
  { id: "TV-204",  tag: "TV-204", type: "Control Valve",       valveType: "Globe, Pneumatic",   body: "WCC",  cv: "44",  action: "Air-to-open",  failPos: "FC", loop: "TIC-204", loopType: "Temp Control",  io: "AO", signal: "4-20mA",      card: "AO-01", slot: "04", channel: "03", addr: "10.0.3.3",  range: "0 – 200 °C",       setpoint: "120",    st: 48 },
];

export function buildRows(project: ProjectLike): BulkRow[] {
  const pid = project?.id ? `CDU-PID-${String(100 + (project.id % 9)).padStart(3, "0")}` : "CDU-PID-001";

  return BASE.map((r, i) => {
    const myPid = i % 3 === 1 ? `CDU-PID-${String(102 + (i % 4)).padStart(3, "0")}` : pid;
    return {
      ...r,
      pid: myPid,
      line: i % 2 === 0 ? `P-12-${100 + i}-CS150` : `P-12-${200 + i}-CS150`,
      size:
        r.type.includes("Transmitter") || r.type.includes("Exchanger")
          ? "—"
          : i % 2 === 0
            ? '4"'
            : '6"',
      sched: r.type.includes("Exchanger") ? "—" : "STD",
      material: r.body !== "—" ? `Body ${r.body}` : "A106 Gr B",
      rating: "ANSI 150",
      insul: r.type.includes("Temp") ? "PIR-50" : "—",
      disc: r.type.includes("Valve") ? "Mech" : "Inst",
      service:
        r.id === "PV-203"
          ? "Crude → E-104"
          : r.id === "FT-101"
            ? "Reflux header"
            : r.id === "FT-202"
              ? "Naphtha overhead"
              : r.id === "PT-201"
                ? "Crude inlet"
                : r.id === "TT-301"
                  ? "CDU column tray 14"
                  : r.id === "LT-401"
                    ? "Reflux drum D-201"
                    : r.id === "E-104"
                      ? "Crude / SR diesel"
                      : r.id === "P-101"
                        ? "Crude charge"
                        : r.id === "PSV-022"
                          ? "Column overpressure"
                          : r.id === "XV-501"
                            ? "ESD trip 5"
                            : "—",
      loc: r.type.includes("Valve") ? "Field, ITR-04" : "JB-22",
      dPress: r.type.includes("Exchanger") ? "1100 kPa" : "—",
      dTemp: r.type.includes("Exchanger") ? "260°C" : "—",
      equipNo: r.type.includes("Exchanger") ? r.id : r.type.includes("Pump") ? r.id : "—",
      equipType: r.type.includes("Exchanger") ? "Shell & Tube" : r.type.includes("Pump") ? "Centrifugal" : "—",
      sheet: String(((i + 4) % 12) + 1).padStart(2, "0"),
      func: r.loopType !== "—" ? r.loopType : "—",
      description:
        r.type === "Control Valve"
          ? "Globe, Air-to-open"
          : r.type === "Flow Transmitter"
            ? "DP type, HART"
            : "—",
      causeTag: r.id === "PV-203" ? "PT-201" : r.id === "XV-501" ? "PT-301" : r.id,
      causeType: r.id === "PV-203" ? "High Press" : r.id === "XV-501" ? "Hi-Hi Press" : "—",
      tripSP: r.id === "PV-203" ? "650 kPa" : r.id === "XV-501" ? "950 kPa" : "—",
      effect1: r.id === "PV-203" ? "Close PV-203" : r.id === "XV-501" ? "Trip ESD 5" : "—",
      effect2: r.id === "PV-203" ? "Trip P-101" : r.id === "XV-501" ? "Isolate train" : "—",
      logic: r.id === "PV-203" ? "2oo3" : r.id === "XV-501" ? "1oo2" : "—",
      bypass: r.id === "PV-203" ? "No" : r.id === "XV-501" ? "No" : "—",
      actuator: "Pneumatic",
    };
  });
}
