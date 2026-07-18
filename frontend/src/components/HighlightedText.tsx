/**
 * Renders source text with a <mark> over the local offset range
 * [start, end). Offsets outside the text render the plain text unmarked —
 * the caller is expected to have shown a provenance warning instead.
 */
export default function HighlightedText({
  text,
  start,
  end,
}: {
  text: string;
  start: number | null;
  end: number | null;
}) {
  if (
    start === null ||
    end === null ||
    !(start >= 0 && start < end && end <= text.length)
  ) {
    return <span className="whitespace-pre-wrap">{text}</span>;
  }
  return (
    <span className="whitespace-pre-wrap">
      {text.slice(0, start)}
      <mark className="rounded box-decoration-clone bg-warning/30 px-0.5 py-0 text-warning-foreground dark:text-warning">
        {text.slice(start, end)}
      </mark>
      {text.slice(end)}
    </span>
  );
}
