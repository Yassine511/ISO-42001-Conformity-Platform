import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import VerdictBadge from "../components/VerdictBadge";
import AbstainReasonLabel from "../components/AbstainReasonLabel";
import HighlightedText from "../components/HighlightedText";

describe("VerdictBadge", () => {
  it("always pairs color with a text label (never color-only)", () => {
    render(<VerdictBadge verdict="non_compliant" />);
    expect(screen.getByText("Non conforme")).toBeInTheDocument();
  });

  it("renders nothing without a verdict", () => {
    const { container } = render(<VerdictBadge verdict={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("AbstainReasonLabel", () => {
  it("renders evidentiary abstentions as amber judgment calls", () => {
    render(<AbstainReasonLabel reason="fuzzy_citation" />);
    const el = screen.getByText(/Citation approximative/);
    expect(el.className).toContain("amber");
  });

  it("renders infrastructure abstentions as neutral service failures", () => {
    render(<AbstainReasonLabel reason="llm_error" />);
    const el = screen.getByText(/Échec technique/);
    expect(el.className).not.toContain("amber");
    expect(el.className).toContain("slate");
  });
});

describe("HighlightedText", () => {
  it("marks exactly the local offset range", () => {
    render(<HighlightedText text="abcdef" start={2} end={4} />);
    const mark = screen.getByText("cd");
    expect(mark.tagName).toBe("MARK");
  });

  it("renders plain text when offsets are out of bounds", () => {
    const { container } = render(<HighlightedText text="abc" start={1} end={99} />);
    expect(container.querySelector("mark")).toBeNull();
    expect(container.textContent).toBe("abc");
  });

  it("renders plain text when offsets are missing", () => {
    const { container } = render(<HighlightedText text="abc" start={null} end={null} />);
    expect(container.querySelector("mark")).toBeNull();
  });
});
