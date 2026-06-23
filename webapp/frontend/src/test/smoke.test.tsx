import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

describe("vitest + RTL smoke", () => {
  it("renders a trivial component", () => {
    render(<div>QONG Studio admin tests up</div>);
    expect(screen.getByText("QONG Studio admin tests up")).toBeInTheDocument();
  });
});
