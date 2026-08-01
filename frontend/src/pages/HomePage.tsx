import { Link, Navigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowRight,
  Boxes,
  FileSearch,
  Gauge,
  GitBranch,
  MessageSquareText,
  Network,
  ShieldAlert,
  Waypoints,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { BrandMark } from "@/components/BrandMark";
import { MigrationFlow } from "@/components/marketing/MigrationFlow";

const NAV_LINKS = [
  { label: "Home", href: "#top" },
  { label: "Capabilities", href: "#capabilities" },
  { label: "About", href: "#about" },
];

const MARQUEE_TOP = [
  "DIGITAL TWIN GRAPH",
  "FAILURE SIMULATION",
  "WAVE SEQUENCING",
  "AI COPILOT",
  "READINESS SCORE",
  "RISK HEATMAP",
];
const MARQUEE_BOTTOM = [
  "DEPENDENCY MAPPING",
  "CASCADING RISK",
  "COST MODELING",
  "DOCUMENT DISCOVERY",
  "BLAST RADIUS",
  "CUTOVER PLANNING",
];

const FEATURES = [
  {
    icon: Network,
    title: "Digital twin graph",
    body: "Every service, database and integration discovered from your own documents and rendered as a live dependency graph - not a spreadsheet guess.",
  },
  {
    icon: Gauge,
    title: "What-if simulation",
    body: "Pick a service and watch the failure cascade before it happens. See exactly which systems, and how much revenue, sit downstream of a bad migration order.",
  },
  {
    icon: GitBranch,
    title: "Wave planner",
    body: "Sequences the migration by dependency depth, risk and cost - so nothing gets cut over before what it relies on.",
  },
  {
    icon: ShieldAlert,
    title: "Readiness & risk scoring",
    body: "One score for how migration-ready a system really is, backed by the same graph and simulation data behind it - not a checklist.",
  },
  {
    icon: MessageSquareText,
    title: "Executive copilot",
    body: "Ask the assessment questions in plain language - cost, blast radius, timeline - and get answers grounded in the actual graph.",
  },
  {
    icon: Boxes,
    title: "Document discovery",
    body: "Upload architecture docs, runbooks or exports. EMIOS extracts systems and dependencies automatically and keeps the graph current.",
  },
] as const;

const PROCESS = [
  {
    icon: FileSearch,
    title: "Discover",
    body: "Upload what you already have - architecture docs, runbooks, exports. EMIOS reads them and extracts the real system graph.",
  },
  {
    icon: Waypoints,
    title: "Simulate",
    body: "Before anything moves, run failure scenarios against the graph and see exactly what breaks, and what it costs.",
  },
  {
    icon: GitBranch,
    title: "Sequence",
    body: "Waves are ordered by dependency depth and risk, not by guesswork - so nothing is cut over before what it relies on.",
  },
] as const;

function Marquee({ items, reverse }: { items: string[]; reverse?: boolean }) {
  const doubled = [...items, ...items];
  return (
    <div className="overflow-hidden py-2">
      <div
        className="flex w-max gap-3 animate-marquee"
        style={reverse ? { animationDirection: "reverse" } : undefined}
      >
        {doubled.map((label, i) => (
          <span
            key={i}
            className="shrink-0 rounded-full border border-border bg-card/60 px-5 py-2 font-mono-ui text-xs tracking-wider text-muted-foreground backdrop-blur-md sm:text-sm"
          >
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function HomePage() {
  const { user } = useAuth();
  if (user) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div id="top" className="relative min-h-screen overflow-x-clip bg-background text-foreground">
      <div className="pointer-events-none fixed inset-0 hidden dark:block dark:bg-noise dark:opacity-[0.04]" />
      <div className="pointer-events-none fixed inset-0 hidden overflow-hidden dark:block">
        <div className="absolute -left-40 -top-40 h-[36rem] w-[36rem] rounded-full bg-[#30E3CA]/[0.14] blur-3xl" />
        <div className="absolute -right-40 top-10 h-[32rem] w-[32rem] rounded-full bg-[#FF204E]/[0.10] blur-3xl" />
        <div className="absolute bottom-[-12rem] left-1/3 h-[34rem] w-[34rem] rounded-full bg-[#DA0037]/[0.07] blur-3xl" />
      </div>

      {/* Nav */}
      <header className="sticky top-0 z-20 border-b border-transparent bg-background/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between px-6 py-5 sm:px-10 lg:px-16">
          <a href="#top" className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-primary text-primary-foreground dark:bg-gradient-to-br dark:from-[#17181a] dark:to-[#0c0c0d] dark:text-[#FF204E]">
              <BrandMark className="h-4.5 w-4.5" />
            </span>
            <span className="font-display text-base font-semibold tracking-wide">EMIOS</span>
          </a>

          <nav className="hidden items-center gap-8 md:flex">
            {NAV_LINKS.map((link) => (
              <a
                key={link.label}
                href={link.href}
                className="font-mono-ui text-xs uppercase tracking-widest text-muted-foreground transition hover:text-foreground"
              >
                {link.label}
              </a>
            ))}
          </nav>

          <Link
            to="/login"
            className="rounded-lg border border-border bg-card/60 px-5 py-2.5 text-sm font-semibold text-foreground backdrop-blur-md transition hover:border-primary/50 hover:text-primary"
          >
            Log in
          </Link>
        </div>
      </header>

      {/* Hero */}
      <section className="relative z-10 mx-auto flex min-h-[92svh] max-w-[1600px] flex-col justify-center px-6 py-16 text-center sm:px-10 lg:px-16">
        <span className="font-mono-ui text-xs uppercase tracking-[0.3em] text-muted-foreground sm:text-sm">
          Migration intelligence platform
        </span>

        <div className="mt-8">
          <Marquee items={MARQUEE_TOP} />
        </div>

        <motion.h1
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: "easeOut" }}
          className="mx-auto mt-6 max-w-6xl text-balance font-display text-6xl font-bold leading-[1.02] tracking-tight sm:text-7xl lg:text-8xl"
        >
          Know what <span className="text-destructive dark:text-[#FF204E]">breaks</span> — before you migrate it.
        </motion.h1>

        <div className="mt-6">
          <Marquee items={MARQUEE_BOTTOM} reverse />
        </div>

        <motion.p
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.15, ease: "easeOut" }}
          className="mx-auto mt-8 max-w-2xl text-balance text-lg text-muted-foreground sm:text-xl"
        >
          EMIOS builds a live digital twin of your stack, simulates cascading failures before a
          single service moves, and sequences the migration so nothing goes down.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.3, ease: "easeOut" }}
          className="mt-10 flex flex-wrap items-center justify-center gap-4"
        >
          <Link
            to="/login"
            className="inline-flex items-center gap-2 rounded-xl bg-destructive px-8 py-4 text-base font-semibold text-white shadow-lg shadow-destructive/25 transition hover:-translate-y-0.5 hover:shadow-destructive/40 dark:bg-[#FF204E] dark:shadow-[#FF204E]/25 dark:hover:shadow-[#FF204E]/40"
          >
            Log in to your assessment <ArrowRight className="h-5 w-5" />
          </Link>
          <a
            href="#capabilities"
            className="inline-flex items-center gap-2 rounded-xl border border-border bg-card/50 px-8 py-4 text-base font-semibold text-foreground backdrop-blur-md transition hover:border-primary/50 hover:text-primary"
          >
            See how it works
          </a>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.9, delay: 0.35, ease: "easeOut" }}
          className="mx-auto mt-16 w-full max-w-5xl rounded-2xl border border-border bg-card/40 p-6 backdrop-blur-md sm:p-10"
        >
          <MigrationFlow className="w-full" />
          <p className="mt-2 font-mono-ui text-xs uppercase tracking-widest text-muted-foreground">
            Legacy stack → target cloud, live on the digital twin graph
          </p>
        </motion.div>
      </section>

      {/* Capabilities */}
      <section id="capabilities" className="relative z-10 mx-auto max-w-[1600px] px-6 py-28 sm:px-10 lg:px-16">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="mx-auto max-w-2xl text-center"
        >
          <h2 className="text-balance font-display text-4xl font-bold sm:text-5xl">
            One assessment, every migration surface.
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Not a slide deck. Every number here comes from the same graph, run against the same
            simulation engine.
          </p>
        </motion.div>

        <div className="mt-16 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 18 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.5, delay: (i % 3) * 0.08 }}
              className="group rounded-2xl border border-border bg-card/50 p-8 backdrop-blur-md transition-all hover:-translate-y-1 hover:border-primary/40"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                <f.icon className="h-6 w-6" />
              </span>
              <h3 className="mt-5 font-display text-xl font-semibold">{f.title}</h3>
              <p className="mt-3 text-base leading-relaxed text-muted-foreground">{f.body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* About */}
      <section id="about" className="relative z-10 mx-auto max-w-[1600px] px-6 py-28 sm:px-10 lg:px-16">
        <div className="grid grid-cols-1 gap-14 lg:grid-cols-2 lg:items-center">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.6 }}
          >
            <span className="font-mono-ui text-xs uppercase tracking-[0.3em] text-primary">About EMIOS</span>
            <h2 className="mt-4 text-balance font-display text-4xl font-bold sm:text-5xl">
              Built because migration plans are usually guesses.
            </h2>
            <p className="mt-6 text-lg leading-relaxed text-muted-foreground">
              Most migration assessments are a stack of interviews and spreadsheets - an educated
              guess dressed up as a plan. EMIOS starts from the system itself: it reads what you
              already have, builds an actual graph of every dependency, and only then works out
              what order things can safely move in.
            </p>
            <p className="mt-4 text-lg leading-relaxed text-muted-foreground">
              Nothing here is a projection pulled from industry averages. The readiness score, the
              cost model, the risk heatmap - all of it comes from your own graph and your own
              simulation runs.
            </p>
          </motion.div>

          <div className="flex flex-col gap-4">
            {PROCESS.map((step, i) => (
              <motion.div
                key={step.title}
                initial={{ opacity: 0, x: 16 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true, margin: "-60px" }}
                transition={{ duration: 0.5, delay: i * 0.1 }}
                className="flex items-start gap-5 rounded-2xl border border-border bg-card/50 p-6 backdrop-blur-md"
              >
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-destructive/10 text-destructive dark:bg-[#FF204E]/10 dark:text-[#FF204E]">
                  <step.icon className="h-6 w-6" />
                </span>
                <div>
                  <h3 className="font-display text-lg font-semibold">{step.title}</h3>
                  <p className="mt-1.5 text-base leading-relaxed text-muted-foreground">{step.body}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="relative z-10 mx-auto max-w-5xl px-6 pb-28 text-center sm:px-10 lg:px-16">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="rounded-3xl border border-border bg-card/50 px-8 py-16 backdrop-blur-md sm:py-20"
        >
          <h2 className="text-balance font-display text-4xl font-bold sm:text-5xl">
            See your own migration's blast radius.
          </h2>
          <p className="mx-auto mt-4 max-w-md text-lg text-muted-foreground">
            Log in to open an assessment, or start a new one once you're in.
          </p>
          <Link
            to="/login"
            className="mt-9 inline-flex items-center gap-2 rounded-xl bg-destructive px-8 py-4 text-base font-semibold text-white shadow-lg shadow-destructive/25 transition hover:-translate-y-0.5 hover:shadow-destructive/40 dark:bg-[#FF204E] dark:shadow-[#FF204E]/25 dark:hover:shadow-[#FF204E]/40"
          >
            Log in <ArrowRight className="h-5 w-5" />
          </Link>
        </motion.div>
      </section>

      <footer className="relative z-10 mx-auto max-w-[1600px] px-6 pb-10 sm:px-10 lg:px-16">
        <div className="flex flex-col items-center justify-between gap-3 border-t border-border pt-6 text-sm text-muted-foreground sm:flex-row">
          <div className="flex items-center gap-2">
            <BrandMark className="h-4 w-4 text-destructive dark:text-[#FF204E]" />
            <span className="font-mono-ui">EMIOS — Migration Intelligence</span>
          </div>
          <span>Built for teams migrating complex systems to the cloud.</span>
        </div>
      </footer>
    </div>
  );
}
