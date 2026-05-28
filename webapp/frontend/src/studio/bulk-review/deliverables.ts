export interface Deliverable {
  key: string;
  icon: string;
  name: string;
  total: number;
  done: number;
}

export interface ColumnDef {
  k: string;
  lbl: string;
  w: string;
  m?: boolean;
  sel?: boolean;
  small?: boolean;
  pct?: boolean;
}

export interface DetailGroup {
  title: string;
  rows: Array<[string, string]>;
}

export const DELIVERABLES: Deliverable[] = [
  { key: "index", icon: "list-checks", name: "Instrument Index", total: 182, done: 182 },
  { key: "datasheet", icon: "file-text", name: "Instrument Datasheet", total: 68, done: 32 },
  { key: "narrative", icon: "scroll-text", name: "Control Narrative", total: 24, done: 16 },
  { key: "cande", icon: "git-merge", name: "Cause & Effect", total: 40, done: 11 },
  { key: "io", icon: "list", name: "I/O List", total: 204, done: 204 },
  { key: "valves", icon: "git-pull-request", name: "Valve List", total: 52, done: 38 },
  { key: "lines", icon: "git-branch", name: "Line List", total: 96, done: 0 },
  { key: "equip", icon: "boxes", name: "Equipment List", total: 22, done: 18 },
  { key: "loop", icon: "repeat", name: "Loop Schedule", total: 30, done: 9 },
  { key: "tags", icon: "tag", name: "Tag Register", total: 204, done: 204 },
];

export const COLUMNS: Record<string, ColumnDef[]> = {
  datasheet: [
    { k: "tag", lbl: "Tag", w: "100px", m: true, sel: true },
    { k: "type", lbl: "Type", w: "1fr" },
    { k: "loop", lbl: "Loop", w: "100px", m: true },
    { k: "pid", lbl: "P&ID", w: "120px", m: true },
    { k: "line", lbl: "Line", w: "150px", m: true, small: true },
    { k: "size", lbl: "Size", w: "60px", m: true },
    { k: "io", lbl: "I/O", w: "60px", m: true },
    { k: "st", lbl: "%", w: "70px", pct: true },
  ],
  index: [
    { k: "tag", lbl: "Tag", w: "100px", m: true, sel: true },
    { k: "type", lbl: "Type", w: "180px" },
    { k: "loop", lbl: "Loop", w: "100px", m: true },
    { k: "disc", lbl: "Discipline", w: "100px" },
    { k: "pid", lbl: "P&ID", w: "120px", m: true },
    { k: "service", lbl: "Service", w: "1fr" },
    { k: "loc", lbl: "Location", w: "140px" },
  ],
  narrative: [
    { k: "loop", lbl: "Loop", w: "100px", m: true, sel: true },
    { k: "loopType", lbl: "Loop Type", w: "140px" },
    { k: "service", lbl: "Service", w: "1fr" },
    { k: "setpoint", lbl: "Setpoint", w: "100px", m: true },
    { k: "range", lbl: "Range", w: "160px", m: true },
    { k: "action", lbl: "Action", w: "100px", m: true },
    { k: "failPos", lbl: "Fail Pos", w: "90px", m: true },
  ],
  cande: [
    { k: "causeTag", lbl: "Cause Tag", w: "110px", m: true, sel: true },
    { k: "causeType", lbl: "Cause", w: "150px" },
    { k: "tripSP", lbl: "Trip SP", w: "100px", m: true },
    { k: "effect1", lbl: "Effect 1", w: "1fr" },
    { k: "effect2", lbl: "Effect 2", w: "1fr" },
    { k: "logic", lbl: "Logic", w: "70px", m: true },
    { k: "bypass", lbl: "Bypass", w: "70px", m: true },
  ],
  io: [
    { k: "tag", lbl: "Tag", w: "100px", m: true, sel: true },
    { k: "io", lbl: "I/O", w: "60px", m: true },
    { k: "signal", lbl: "Signal", w: "140px", m: true },
    { k: "card", lbl: "Card", w: "80px", m: true },
    { k: "slot", lbl: "Slot", w: "60px", m: true },
    { k: "channel", lbl: "Channel", w: "80px", m: true },
    { k: "addr", lbl: "Address", w: "110px", m: true },
    { k: "range", lbl: "Range", w: "1fr", m: true, small: true },
  ],
  valves: [
    { k: "tag", lbl: "Tag", w: "100px", m: true, sel: true },
    { k: "valveType", lbl: "Valve Type", w: "1fr" },
    { k: "size", lbl: "Size", w: "60px", m: true },
    { k: "body", lbl: "Body", w: "90px", m: true },
    { k: "cv", lbl: "Cv", w: "70px", m: true },
    { k: "action", lbl: "Action", w: "110px", m: true },
    { k: "failPos", lbl: "Fail Pos", w: "90px", m: true },
    { k: "rating", lbl: "Rating", w: "110px", m: true },
  ],
  lines: [
    { k: "line", lbl: "Line No", w: "150px", m: true, sel: true },
    { k: "service", lbl: "Service", w: "1fr" },
    { k: "size", lbl: "Size", w: "60px", m: true },
    { k: "sched", lbl: "Sched", w: "70px", m: true },
    { k: "material", lbl: "Material", w: "110px", m: true },
    { k: "rating", lbl: "Rating", w: "110px", m: true },
    { k: "insul", lbl: "Insul", w: "70px" },
  ],
  equip: [
    { k: "equipNo", lbl: "Equip No", w: "110px", m: true, sel: true },
    { k: "equipType", lbl: "Type", w: "180px" },
    { k: "service", lbl: "Service", w: "1fr" },
    { k: "dPress", lbl: "Design P", w: "100px", m: true },
    { k: "dTemp", lbl: "Design T", w: "100px", m: true },
    { k: "material", lbl: "Material", w: "120px", m: true },
  ],
  loop: [
    { k: "loop", lbl: "Loop", w: "100px", m: true, sel: true },
    { k: "loopType", lbl: "Type", w: "140px" },
    { k: "service", lbl: "Service", w: "1fr" },
    { k: "pid", lbl: "P&ID", w: "120px", m: true },
    { k: "sheet", lbl: "Sheet", w: "70px", m: true },
    { k: "func", lbl: "Function", w: "160px" },
  ],
  tags: [
    { k: "tag", lbl: "Tag", w: "100px", m: true, sel: true },
    { k: "type", lbl: "Type", w: "160px" },
    { k: "disc", lbl: "Disc", w: "80px" },
    { k: "pid", lbl: "P&ID", w: "120px", m: true },
    { k: "description", lbl: "Description", w: "1fr" },
  ],
};

export const DETAIL_GROUPS: Record<string, DetailGroup[]> = {
  datasheet: [
    { title: "Identification", rows: [["Tag", "tag"], ["Loop #", "loop"], ["Type", "type"]] },
    { title: "P&ID Reference", rows: [["P&ID", "pid"], ["Line No", "line"], ["Size", "size"]] },
    { title: "Signal & I/O", rows: [["I/O Type", "io"], ["Signal", "signal"]] },
    { title: "Status", rows: [["Completion", "st%"]] },
  ],
  index: [
    {
      title: "Identification",
      rows: [["Tag", "tag"], ["Type", "type"], ["Loop", "loop"], ["Discipline", "disc"]],
    },
    { title: "Reference", rows: [["P&ID", "pid"], ["Location", "loc"], ["Service", "service"]] },
  ],
  narrative: [
    { title: "Loop", rows: [["Loop #", "loop"], ["Loop Type", "loopType"], ["Service", "service"]] },
    {
      title: "Control",
      rows: [["Setpoint", "setpoint"], ["Range", "range"], ["Action", "action"], ["Fail Pos", "failPos"]],
    },
  ],
  cande: [
    { title: "Cause", rows: [["Cause Tag", "causeTag"], ["Cause", "causeType"], ["Trip SP", "tripSP"]] },
    {
      title: "Effects",
      rows: [["Effect 1", "effect1"], ["Effect 2", "effect2"], ["Logic", "logic"], ["Bypass", "bypass"]],
    },
  ],
  io: [
    { title: "Signal", rows: [["Tag", "tag"], ["I/O Type", "io"], ["Signal", "signal"]] },
    {
      title: "DCS Address",
      rows: [["Card", "card"], ["Slot", "slot"], ["Channel", "channel"], ["Address", "addr"]],
    },
    { title: "Engineering", rows: [["Range", "range"]] },
  ],
  valves: [
    { title: "Identification", rows: [["Tag", "tag"], ["Valve Type", "valveType"], ["Size", "size"]] },
    { title: "Construction", rows: [["Body", "body"], ["Rating", "rating"]] },
    { title: "Performance", rows: [["Cv", "cv"], ["Action", "action"], ["Fail Pos", "failPos"]] },
  ],
  lines: [
    {
      title: "Line",
      rows: [["Line No", "line"], ["Service", "service"], ["Size", "size"], ["Sched", "sched"]],
    },
    {
      title: "Material",
      rows: [["Material", "material"], ["Rating", "rating"], ["Insulation", "insul"]],
    },
  ],
  equip: [
    {
      title: "Equipment",
      rows: [["Equip No", "equipNo"], ["Type", "equipType"], ["Service", "service"]],
    },
    {
      title: "Design",
      rows: [["Design Press", "dPress"], ["Design Temp", "dTemp"], ["Material", "material"]],
    },
  ],
  loop: [
    { title: "Loop", rows: [["Loop", "loop"], ["Type", "loopType"], ["Service", "service"]] },
    { title: "Reference", rows: [["P&ID", "pid"], ["Sheet", "sheet"], ["Function", "func"]] },
  ],
  tags: [
    { title: "Tag", rows: [["Tag", "tag"], ["Type", "type"], ["Discipline", "disc"]] },
    { title: "Reference", rows: [["P&ID", "pid"], ["Description", "description"]] },
  ],
};
