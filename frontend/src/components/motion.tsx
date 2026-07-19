import type { ReactNode } from "react";
import { LazyMotion, domAnimation, m, MotionConfig } from "framer-motion";

/** Global motion context — `reducedMotion="user"` disables transform/opacity
    animation whenever the OS asks for reduced motion. */
export function MotionRoot({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={domAnimation}>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </LazyMotion>
  );
}

const EASE = [0.32, 0.72, 0, 1] as const;

/** Gentle page-level entrance: fade + 12px rise. */
export function PageFade({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <m.div
      className={className}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: EASE }}
    >
      {children}
    </m.div>
  );
}

/** Staggered container for KPI rows / card grids. */
export function StaggerGroup({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <m.div
      className={className}
      initial="hidden"
      animate="show"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.06 } } }}
    >
      {children}
    </m.div>
  );
}

/** Scroll-triggered cascade reveal (the design-lab `.reveal` / `--i`
    contract): fade + 14px rise the first time the element enters the
    viewport, delayed by `i` × 90 ms so sibling blocks waterfall. */
export function Reveal({
  children,
  className,
  i = 0,
}: {
  children: ReactNode;
  className?: string;
  i?: number;
}) {
  return (
    <m.div
      className={className}
      initial={{ opacity: 0, y: 14 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.12 }}
      transition={{ duration: 0.55, ease: EASE, delay: i * 0.09 }}
    >
      {children}
    </m.div>
  );
}

export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <m.div
      className={className}
      variants={{
        hidden: { opacity: 0, y: 10 },
        show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: EASE } },
      }}
    >
      {children}
    </m.div>
  );
}
