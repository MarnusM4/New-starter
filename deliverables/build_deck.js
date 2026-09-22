const pptxgen = require("pptxgenjs");
const p = new pptxgen();
p.defineLayout({ name: "WIDE", width: 13.333, height: 7.5 });
p.layout = "WIDE";

// ---- Palette (Midnight Executive) ----
const NAVY = "1E2761";
const NAVY2 = "2A3576";
const ICE = "CADCFC";
const CARD = "EEF3FF";
const WHITE = "FFFFFF";
const ACCENT = "4A6FE3";
const ACCENTL = "9FC0FF";
const TEXT = "23263B";
const MUTED = "6B7280";
const TITLE_FONT = "Cambria";
const BODY = "Calibri";
const W = 13.333;

// ---------------- Slide 1: Title ----------------
let s = p.addSlide();
s.background = { color: NAVY };
s.addText("CONOSCO", { x: 0.8, y: 0.7, w: 6, h: 0.4, fontFace: BODY, fontSize: 16, bold: true,
  color: ICE, charSpacing: 4 });
s.addShape(p.ShapeType.rect, { x: 0, y: 5.55, w: W, h: 0.06, fill: { color: ACCENT } });
s.addText("Automating Starter / Leaver Provisioning", { x: 0.8, y: 2.0, w: 11.7, h: 1.6,
  fontFace: TITLE_FONT, fontSize: 44, bold: true, color: WHITE });
s.addText("Getting our clients’ new joiners and leavers done on time — every time",
  { x: 0.8, y: 3.6, w: 11.5, h: 0.9, fontFace: BODY, fontSize: 18, italic: true, color: ICE });
s.addText([
  { text: "Proposal for leadership review", options: { bold: true, color: WHITE } },
  { text: "      Marnus van der Hoven · Support Technician · 18 June 2026", options: { color: ICE } },
], { x: 0.8, y: 5.8, w: 11.7, h: 0.5, fontFace: BODY, fontSize: 13 });

// ---------------- Slide 2: What this means for clients (core message) ----------------
s = p.addSlide();
s.background = { color: NAVY };
s.addText("What this means for our clients", { x: 0.7, y: 0.55, w: 11.9, h: 0.7,
  fontFace: TITLE_FONT, fontSize: 30, bold: true, color: ICE });
s.addText("Starters and leavers, done on time — every time.", { x: 0.7, y: 1.7, w: 11.9, h: 1.1,
  fontFace: TITLE_FONT, fontSize: 40, bold: true, color: WHITE });
const msg = [
  ["No waiting for a technician", "provisioning starts the instant the ticket is logged"],
  ["The same correct setup, every time", "no missed licenses, groups or permissions"],
  ["Leavers removed promptly", "the security response clients expect"],
];
msg.forEach((m, i) => {
  const x = 0.7 + i * 4.05;
  s.addShape(p.ShapeType.roundRect, { x, y: 3.5, w: 3.75, h: 2.4, fill: { color: NAVY2 },
    line: { color: NAVY2 }, rectRadius: 0.08 });
  s.addShape(p.ShapeType.ellipse, { x: x + 0.3, y: 3.8, w: 0.5, h: 0.5, fill: { color: ACCENT } });
  s.addText(String(i + 1), { x: x + 0.3, y: 3.8, w: 0.5, h: 0.5, align: "center", valign: "middle",
    fontFace: BODY, fontSize: 18, bold: true, color: WHITE });
  s.addText(m[0], { x: x + 0.3, y: 4.45, w: 3.2, h: 0.8, fontFace: TITLE_FONT, fontSize: 17, bold: true, color: WHITE });
  s.addText(m[1], { x: x + 0.3, y: 5.25, w: 3.2, h: 0.55, fontFace: BODY, fontSize: 12.5, color: ICE });
});

// ---------------- Slide 3: The problem today ----------------
s = p.addSlide();
s.background = { color: WHITE };
s.addText("The problem today", { x: 0.7, y: 0.5, w: 11.9, h: 0.8, fontFace: TITLE_FONT, fontSize: 34, bold: true, color: NAVY });
s.addText("The manual process works, but it limits the experience we can give clients",
  { x: 0.7, y: 1.25, w: 11.9, h: 0.5, fontFace: BODY, fontSize: 16, color: MUTED });
const probs = [
  ["Clients wait", "provisioning only happens when a technician is free — at busy times, starters and leavers queue"],
  ["Inconsistent", "each client’s process differs, so the result depends on who picks up the ticket"],
  ["Mistakes show", "a missed license or wrong permission is something the client notices"],
  ["Leaver risk", "access can linger in the queue — a security concern for the client"],
];
const cw = 2.85, gap = 0.25, sx = 0.7, cy = 2.1, ch = 2.7;
probs.forEach((c, i) => {
  const x = sx + i * (cw + gap);
  s.addShape(p.ShapeType.roundRect, { x, y: cy, w: cw, h: ch, fill: { color: CARD }, line: { color: CARD }, rectRadius: 0.08 });
  s.addShape(p.ShapeType.ellipse, { x: x + 0.25, y: cy + 0.28, w: 0.55, h: 0.55, fill: { color: NAVY } });
  s.addText(String(i + 1), { x: x + 0.25, y: cy + 0.28, w: 0.55, h: 0.55, align: "center", valign: "middle", fontFace: BODY, fontSize: 18, bold: true, color: WHITE });
  s.addText(c[0], { x: x + 0.25, y: cy + 1.0, w: cw - 0.5, h: 0.5, fontFace: TITLE_FONT, fontSize: 18, bold: true, color: NAVY });
  s.addText(c[1], { x: x + 0.25, y: cy + 1.5, w: cw - 0.5, h: 1.1, fontFace: BODY, fontSize: 12.5, color: TEXT });
});
s.addText("And every hour spent on manual setup is an hour not spent on other clients’ tickets.",
  { x: 0.7, y: 5.2, w: 11.9, h: 0.5, fontFace: BODY, fontSize: 15, italic: true, color: NAVY });

// ---------------- Slide 4: How it works ----------------
s = p.addSlide();
s.background = { color: WHITE };
s.addText("How it works", { x: 0.7, y: 0.5, w: 11.9, h: 0.8, fontFace: TITLE_FONT, fontSize: 34, bold: true, color: NAVY });
s.addText("Triggered automatically by HALO — runs end-to-end, with a technician approving the change",
  { x: 0.7, y: 1.25, w: 11.9, h: 0.5, fontFace: BODY, fontSize: 16, color: MUTED });
const steps = [
  ["1", "Ticket logged", "Client logs a starter/leaver ticket in HALO"],
  ["2", "Agent reads it", "Identifies the client and follows their exact process"],
  ["3", "Plan + approval", "Posts the exact plan; a technician approves"],
  ["4", "Done + recorded", "Creates/disables the account & access, writes back"],
];
const sw = 2.75, sgap = 0.45, sx0 = 0.7, sy = 2.5, sh = 2.4;
steps.forEach((st, i) => {
  const x = sx0 + i * (sw + sgap);
  s.addShape(p.ShapeType.roundRect, { x, y: sy, w: sw, h: sh, fill: { color: i % 2 ? CARD : "E3ECFF" }, line: { color: ICE }, rectRadius: 0.08 });
  s.addShape(p.ShapeType.ellipse, { x: x + sw / 2 - 0.35, y: sy + 0.25, w: 0.7, h: 0.7, fill: { color: NAVY } });
  s.addText(st[0], { x: x + sw / 2 - 0.35, y: sy + 0.25, w: 0.7, h: 0.7, align: "center", valign: "middle", fontFace: TITLE_FONT, fontSize: 24, bold: true, color: WHITE });
  s.addText(st[1], { x: x + 0.2, y: sy + 1.05, w: sw - 0.4, h: 0.5, align: "center", fontFace: TITLE_FONT, fontSize: 16, bold: true, color: NAVY });
  s.addText(st[2], { x: x + 0.2, y: sy + 1.5, w: sw - 0.4, h: 0.8, align: "center", fontFace: BODY, fontSize: 12.5, color: TEXT });
  if (i < steps.length - 1) s.addText("→", { x: x + sw, y: sy + 0.7, w: sgap, h: 0.7, align: "center", valign: "middle", fontFace: BODY, fontSize: 26, bold: true, color: ACCENT });
});
s.addText("Works for both cloud-only (Microsoft Entra) and on-premises Active Directory clients — automatically, per client.",
  { x: 0.7, y: 5.4, w: 11.9, h: 0.5, fontFace: BODY, fontSize: 14, italic: true, color: NAVY });

// ---------------- Slide 5: What changes for the client ----------------
s = p.addSlide();
s.background = { color: WHITE };
s.addText("What changes for the client", { x: 0.7, y: 0.5, w: 11.9, h: 0.8, fontFace: TITLE_FONT, fontSize: 34, bold: true, color: NAVY });
const bens = [
  ["On time, every time", "ready for the new joiner’s first day — no waiting"],
  ["No queue wait", "not stuck behind other tickets in the support queue"],
  ["Error-free", "the same correct setup applied every single time"],
  ["Leavers handled promptly", "access removed without delay — security clients expect"],
  ["Whole service speeds up", "technicians freed to resolve other client tickets faster"],
  ["A consistent standard", "the same high quality across every client"],
];
const bw = 3.75, bh = 1.55, bgap = 0.3, bx0 = 0.7, by0 = 1.7;
bens.forEach((b, i) => {
  const col = i % 3, row = Math.floor(i / 3);
  const x = bx0 + col * (bw + bgap), y = by0 + row * (bh + 0.35);
  s.addShape(p.ShapeType.roundRect, { x, y, w: bw, h: bh, fill: { color: CARD }, line: { color: CARD }, rectRadius: 0.08 });
  s.addShape(p.ShapeType.ellipse, { x: x + 0.25, y: y + 0.3, w: 0.35, h: 0.35, fill: { color: ACCENT } });
  s.addText(b[0], { x: x + 0.75, y: y + 0.22, w: bw - 0.95, h: 0.5, fontFace: TITLE_FONT, fontSize: 15.5, bold: true, color: NAVY });
  s.addText(b[1], { x: x + 0.3, y: y + 0.75, w: bw - 0.55, h: 0.7, fontFace: BODY, fontSize: 12.5, color: TEXT });
});
s.addText("Better for the client onboarding — and for every other client whose ticket gets attention sooner.",
  { x: 0.7, y: 5.95, w: 11.9, h: 0.5, fontFace: BODY, fontSize: 15, italic: true, color: NAVY });

// ---------------- Slide 6: Faster turnaround + time returned ----------------
s = p.addSlide();
s.background = { color: WHITE };
s.addText("Faster turnaround, time given back", { x: 0.7, y: 0.5, w: 11.9, h: 0.8, fontFace: TITLE_FONT, fontSize: 34, bold: true, color: NAVY });

// Left: turnaround
s.addShape(p.ShapeType.roundRect, { x: 0.7, y: 1.7, w: 5.4, h: 4.1, fill: { color: NAVY }, line: { color: NAVY }, rectRadius: 0.08 });
s.addText("For the client", { x: 1.0, y: 2.0, w: 4.8, h: 0.5, fontFace: BODY, fontSize: 15, bold: true, color: ICE });
s.addText("1–2 hours", { x: 1.0, y: 2.5, w: 4.8, h: 0.9, fontFace: TITLE_FONT, fontSize: 40, bold: true, color: WHITE });
s.addText("of technician work — only once one is free", { x: 1.0, y: 3.35, w: 4.8, h: 0.5, fontFace: BODY, fontSize: 13, color: ICE });
s.addText("becomes", { x: 1.0, y: 3.95, w: 4.8, h: 0.4, fontFace: BODY, fontSize: 14, italic: true, color: ICE });
s.addText("minutes", { x: 1.0, y: 4.35, w: 4.8, h: 0.9, fontFace: TITLE_FONT, fontSize: 40, bold: true, color: ACCENTL });
s.addText("automatically, the moment the ticket is logged", { x: 1.0, y: 5.2, w: 4.8, h: 0.5, fontFace: BODY, fontSize: 13, color: ICE });

// Right: time returned to the team (hours, no money)
s.addText("Technician time returned to other client tickets", { x: 6.5, y: 1.7, w: 6.1, h: 0.5, fontFace: TITLE_FONT, fontSize: 16, bold: true, color: NAVY });
const ret = [["20 starters / month", "≈ 30 hours / month"], ["50 starters / month", "≈ 75 hours / month"], ["100 starters / month", "≈ 150 hours / month"]];
ret.forEach((r, i) => {
  const y = 2.4 + i * 1.05;
  s.addShape(p.ShapeType.roundRect, { x: 6.5, y, w: 6.1, h: 0.9, fill: { color: CARD }, line: { color: ICE }, rectRadius: 0.06 });
  s.addText(r[0], { x: 6.75, y, w: 3.3, h: 0.9, valign: "middle", fontFace: BODY, fontSize: 14, color: TEXT });
  s.addText(r[1], { x: 9.9, y, w: 2.5, h: 0.9, valign: "middle", align: "right", fontFace: TITLE_FONT, fontSize: 20, bold: true, color: NAVY });
});
s.addText("Volumes are placeholders until we confirm our figures. Leavers add further time on top.",
  { x: 6.5, y: 5.65, w: 6.1, h: 0.5, fontFace: BODY, fontSize: 11.5, italic: true, color: MUTED });

// ---------------- Slide 7: Security / trust ----------------
s = p.addSlide();
s.background = { color: WHITE };
s.addText("Built security-first", { x: 0.7, y: 0.5, w: 11.9, h: 0.8, fontFace: TITLE_FONT, fontSize: 34, bold: true, color: NAVY });
s.addText("Safeguards designed in from the start — the assurance clients’ security reviews look for",
  { x: 0.7, y: 1.25, w: 11.9, h: 0.5, fontFace: BODY, fontSize: 16, color: MUTED });
const sec = [
  ["Human approval gate", "no account is created or disabled without a technician approving"],
  ["Least privilege per client", "separate scoped credentials — no single all-powerful login"],
  ["Secrets in a secure vault", "credentials never live in code or tickets"],
  ["Tickets treated as data", "malicious ticket text can’t trigger unintended actions"],
  ["Full audit trail", "every action recorded against the ticket for client reviews"],
  ["Unknowns flagged, not guessed", "anything unexpected is escalated to a human"],
];
const yrow = 1.95;
sec.forEach((it, i) => {
  const col = i % 2, row = Math.floor(i / 2);
  const x = 0.7 + col * 6.0, y = yrow + row * 1.25;
  s.addShape(p.ShapeType.ellipse, { x, y: y + 0.05, w: 0.45, h: 0.45, fill: { color: NAVY } });
  s.addText("✓", { x, y: y + 0.05, w: 0.45, h: 0.45, align: "center", valign: "middle", fontFace: BODY, fontSize: 18, bold: true, color: WHITE });
  s.addText(it[0], { x: x + 0.6, y: y - 0.05, w: 5.2, h: 0.45, fontFace: TITLE_FONT, fontSize: 16, bold: true, color: NAVY });
  s.addText(it[1], { x: x + 0.6, y: y + 0.4, w: 5.2, h: 0.6, fontFace: BODY, fontSize: 12.5, color: TEXT });
});

// ---------------- Slide 8: Status + ask ----------------
s = p.addSlide();
s.background = { color: NAVY };
s.addText("Where we are — and what we need", { x: 0.7, y: 0.55, w: 11.9, h: 0.8, fontFace: TITLE_FONT, fontSize: 32, bold: true, color: WHITE });
s.addText("Already built (prototype, tested)", { x: 0.7, y: 1.7, w: 5.8, h: 0.5, fontFace: TITLE_FONT, fontSize: 18, bold: true, color: ICE });
["Trigger from HALO + per-client routing", "Account creation — Entra & on-prem AD", "Approval gate, write-back & audit log", "Safety-net retry + security hardening"].forEach((t, i) => {
  s.addText("✓  " + t, { x: 0.7, y: 2.25 + i * 0.5, w: 5.8, h: 0.45, fontFace: BODY, fontSize: 14, color: WHITE });
});
s.addText("To go live, we need", { x: 7.0, y: 1.7, w: 5.6, h: 0.5, fontFace: TITLE_FONT, fontSize: 18, bold: true, color: ICE });
["Approval for a limited pilot", "HALO API access + ticket field details", "Microsoft (Entra) access + secure vault", "Our monthly starter/leaver volumes"].forEach((t, i) => {
  s.addText("•  " + t, { x: 7.0, y: 2.25 + i * 0.5, w: 5.6, h: 0.45, fontFace: BODY, fontSize: 14, color: WHITE });
});
s.addShape(p.ShapeType.roundRect, { x: 0.7, y: 4.9, w: 11.9, h: 1.4, fill: { color: NAVY2 }, line: { color: ACCENT }, rectRadius: 0.08 });
s.addText("Recommendation: approve a limited pilot with 1–2 clients.", { x: 1.0, y: 5.1, w: 11.3, h: 0.5, fontFace: TITLE_FONT, fontSize: 19, bold: true, color: WHITE });
s.addText("Build risk is low — the prototype exists — and the client benefit is immediate: starters and leavers done on time, every time.",
  { x: 1.0, y: 5.6, w: 11.3, h: 0.6, fontFace: BODY, fontSize: 14, color: ICE });

p.writeFile({ fileName: __dirname + "/Conosco-Starter-Leaver-Agent-Overview.pptx" }).then(() => console.log("written deck"));
