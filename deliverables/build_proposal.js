const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, LevelFormat, HeadingLevel, BorderStyle, WidthType, ShadingType,
  PageNumber, Footer, TableOfContents, PageBreak,
} = require("docx");

const BLUE = "1F4E79";
const GREY = "595959";
const CW = 9026; // A4 content width, 1" margins

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };

function h1(text) { return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(text)] }); }
function h2(text) { return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] }); }
function p(text, opts = {}) { return new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text, ...opts })] }); }
function bullet(text) { return new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun(text)] }); }
function numbered(text) { return new Paragraph({ numbering: { reference: "numbers", level: 0 }, children: [new TextRun(text)] }); }

function cell(text, { widthDxa, head = false, bold = false, fill } = {}) {
  return new TableCell({
    borders, margins: cellMargins,
    width: { size: widthDxa, type: WidthType.DXA },
    shading: fill ? { fill, type: ShadingType.CLEAR } : (head ? { fill: BLUE, type: ShadingType.CLEAR } : undefined),
    children: [new Paragraph({ children: [new TextRun({ text, bold: head || bold, color: head ? "FFFFFF" : undefined })] })],
  });
}
function table(headers, rows, widths) {
  const trows = [];
  trows.push(new TableRow({ tableHeader: true, children: headers.map((t, i) => cell(t, { widthDxa: widths[i], head: true })) }));
  rows.forEach((r, ri) => {
    trows.push(new TableRow({ children: r.map((t, i) => cell(String(t), { widthDxa: widths[i], fill: ri % 2 ? "F2F7FB" : undefined })) }));
  });
  return new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: widths, rows: trows });
}

const doc = new Document({
  creator: "Conosco — Marnus van der Hoven",
  title: "Automated Starter / Leaver Provisioning — Proposal",
  styles: {
    default: { document: { run: { font: "Arial", size: 22, color: "222222" } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, color: BLUE, font: "Arial" },
        paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 25, bold: true, color: "2E5C8A", font: "Arial" },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 280 } } } }] },
      { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 280 } } } }] },
    ],
  },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Conosco  ·  Automated Starter / Leaver Provisioning  ·  Page ", size: 16, color: GREY }),
        new TextRun({ children: [PageNumber.CURRENT], size: 16, color: GREY })] })] }) },
    children: [
      // ---- Title block ----
      new Paragraph({ spacing: { before: 1500, after: 0 }, alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "CONOSCO", bold: true, size: 30, color: GREY, characterSpacing: 60 })] }),
      new Paragraph({ spacing: { before: 320, after: 0 }, alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "Automated Starter / Leaver Provisioning", bold: true, size: 46, color: BLUE })] }),
      new Paragraph({ spacing: { before: 160, after: 0 }, alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "Getting our clients’ new joiners and leavers done on time, every time", size: 26, color: GREY, italics: true })] }),
      new Paragraph({ spacing: { before: 900 }, alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "Proposal for Leadership Review", bold: true, size: 24 })] }),
      new Paragraph({ spacing: { before: 120 }, alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "Prepared by: Marnus van der Hoven, Support Technician", size: 20, color: GREY })] }),
      new Paragraph({ spacing: { before: 40 }, alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "Date: 18 June 2026   ·   Status: Draft for discussion", size: 20, color: GREY })] }),
      new Paragraph({ children: [new PageBreak()] }),

      // ---- TOC ----
      new Paragraph({ children: [new TextRun({ text: "Contents", bold: true, size: 28, color: BLUE })], spacing: { after: 120 } }),
      new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }),
      new Paragraph({ children: [new PageBreak()] }),

      // ---- Executive summary ----
      h1("1. Executive summary"),
      p("When a client onboards a new employee (a “starter”) or someone leaves (a “leaver”), they expect the account, access and tools to be ready exactly when needed. Today, that depends on a support technician being free to work the ticket by hand — which can mean a new joiner waiting, or a leaver’s access staying live longer than it should."),
      p("This proposal recommends an AI agent that carries out starter and leaver provisioning automatically the moment the ticket is logged in HALO. It identifies the client, follows that client’s exact process, creates or removes the account and access across Microsoft Entra or on-premises Active Directory, and records everything back to the ticket — with a technician approving before any change is made."),
      p("The headline benefit is client experience: provisioning happens on time, every time, without waiting for a technician to become available, and without the small mistakes that create a poor first impression. A working prototype already exists; the remaining work is to connect it to our live HALO and Microsoft systems and run a pilot."),

      // ---- Why this matters to clients ----
      h1("2. Why this matters to our clients"),
      p("For our clients, starters and leavers are high-visibility moments. A smooth start tells a new employee the IT “just works”; a fumbled one is remembered. This agent improves that experience directly:"),
      bullet("On time, every time — provisioning runs the instant the ticket is logged, so a new joiner is ready for day one rather than waiting for a technician to be free."),
      bullet("No queue dependency — the client no longer waits behind whatever else is in the support queue."),
      bullet("Leavers handled promptly — access is removed without delay, which clients increasingly expect for security and compliance."),
      bullet("Consistent and correct — the same high standard for every client, every time, with no missed licenses or permissions."),
      bullet("No human error — the agent applies the defined process exactly; it doesn’t forget a step or mistype an entry."),

      // ---- The problem today ----
      h1("3. The problem today"),
      p("The current manual process works, but it limits the client experience we can offer:"),
      bullet("Provisioning only happens when a technician is available — at busy times, starters and leavers wait."),
      bullet("Each client’s process is different, so the outcome depends on who picks up the ticket and whether they remember every step."),
      bullet("Manual steps mean occasional mistakes — a missed license or wrong group — which the client notices and which generate follow-up tickets."),
      bullet("Leaver access can linger if the ticket sits in a queue, which is a security and compliance concern for the client."),
      bullet("Technicians spend hours on repetitive setup instead of resolving other client issues, so the whole support queue moves more slowly."),

      // ---- Solution ----
      h1("4. The proposed solution"),
      p("An AI agent, triggered automatically by HALO, that performs the provisioning process end-to-end under human approval:"),
      numbered("A starter/leaver ticket is logged in HALO by the client."),
      numbered("HALO instantly notifies the agent (via a secure webhook) — no waiting for a technician to pick it up."),
      numbered("The agent reads the details and identifies which client logged the ticket."),
      numbered("It follows that client’s exact process — the right identity platform (cloud Entra or on-premises AD), licenses, groups and permissions."),
      numbered("It posts the precise plan to the ticket for a technician to approve."),
      numbered("On approval, it creates (or, for leavers, disables) the account and access, and writes the outcome back to the ticket."),
      p("Each client’s process is stored in its own configuration, so the agent automatically does the right thing for that client — a technician no longer has to remember the differences."),

      // ---- Time and capacity ----
      h1("5. Faster turnaround and freed-up capacity"),
      p("The agent changes provisioning from “whenever a technician is free” to “within minutes of the request,” at any time of day. The cost today is measured in time — both the client’s waiting time and the technician hours consumed."),
      h2("5.1 Turnaround for the client"),
      p("A starter that currently takes a technician one to two hours of hands-on work — and often waits in the queue before that — is completed automatically in minutes. The client’s new joiner is ready on time, consistently."),
      h2("5.2 Technician time returned to other client tickets"),
      p("Every starter the agent handles is technician time given back to the rest of the support queue, so other clients’ tickets are resolved faster too. The table below shows the time returned (using a conservative average of 1.5 hours of hands-on work per starter). Volumes are placeholders until we confirm our monthly figures; leavers add further time on top."),
      table(
        ["Starters / month", "Technician time returned / month", "Technician time returned / year"],
        [
          ["20", "≈ 30 hours", "≈ 360 hours"],
          ["50", "≈ 75 hours", "≈ 900 hours"],
          ["100", "≈ 150 hours", "≈ 1,800 hours"],
        ],
        [3008, 3009, 3009],
      ),
      new Paragraph({ spacing: { before: 100, after: 120 },
        children: [new TextRun({ text: "That reclaimed time is redirected to resolving other client tickets — improving the experience across the whole client base, not just for starters and leavers.", italics: true, size: 18, color: GREY })] }),

      // ---- Security ----
      h1("6. Security and client trust"),
      p("Because the agent has privileged access to user accounts, it is designed security-first — which is itself part of the client experience clients increasingly expect:"),
      bullet("Human approval gate: no account is created or disabled without a technician approving the plan."),
      bullet("Least privilege, per client: separate, scoped credentials per client — no single all-powerful login."),
      bullet("Secrets kept in a secure vault, never in code or tickets."),
      bullet("Ticket content is treated as data, not instructions, so a malicious ticket cannot trigger unintended actions."),
      bullet("A complete audit trail of every action, tied to the ticket — useful evidence for client security reviews."),
      bullet("Anything unexpected (e.g. an unrecognised client) is escalated to a human rather than guessed."),

      // ---- Status ----
      h1("7. Current status and plan"),
      p("A working prototype has already been built and tested, with automated tests passing. The core — trigger, per-client routing, account creation for both identity platforms, approval gate, write-back, audit, and a safety-net retry mechanism — is complete in development."),
      table(
        ["Stage", "Status"],
        [
          ["Trigger from HALO + read & decide", "Built (dev)"],
          ["Account creation — Entra & on-prem AD", "Built (dev)"],
          ["Approval gate, write-back & audit", "Built (dev)"],
          ["Safety-net reconciliation + hardening", "Built (dev)"],
          ["Connect to live HALO + Microsoft systems", "Pending access & approval"],
          ["Leaver process", "Planned next phase"],
        ],
        [5500, 3526],
      ),

      // ---- Asks ----
      h1("8. What we need to proceed"),
      numbered("Approval in principle to move from prototype to a live pilot."),
      numbered("HALO API access and confirmation of the starter/leaver ticket fields."),
      numbered("Microsoft (Entra) application access for the pilot client(s), and a secure vault for secrets."),
      numbered("Our monthly starter/leaver volumes, to quantify the turnaround and capacity benefits."),
      numbered("One or two pilot clients to prove the improved experience before wider rollout."),
      new Paragraph({ spacing: { before: 200 },
        children: [new TextRun({ text: "Recommendation: approve a limited pilot. Build risk is low — the prototype already exists — and the client-experience improvement is immediate: starters and leavers done on time, every time.", bold: true, color: BLUE })] }),
    ],
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(__dirname + "/Conosco-Starter-Leaver-Agent-Proposal.docx", buf);
  console.log("written proposal");
});
