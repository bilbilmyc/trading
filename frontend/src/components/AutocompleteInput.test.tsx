import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { AutocompleteInput } from "./AutocompleteInput";

const OPTIONS = [
  { value: "BTCUSDT", description: "BTC / USDT", keywords: ["btc"] },
  { value: "ETHUSDT", description: "ETH / USDT", keywords: ["eth"] },
  { value: "SOLUSDT", description: "SOL / USDT", keywords: ["sol"] },
];

function Harness() {
  const [value, setValue] = useState("");
  return (
    <>
      <AutocompleteInput
        value={value}
        onChange={setValue}
        options={OPTIONS}
        aria-label="合约代码"
      />
      <output>{value}</output>
    </>
  );
}

describe("AutocompleteInput", () => {
  it("filters symbols as the trader types and chooses the active candidate with Enter", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const input = screen.getByRole("combobox", { name: "合约代码" });
    await user.click(input);
    await user.type(input, "et");

    expect(screen.getByRole("option", { name: /ETHUSDT/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /BTCUSDT/ })).not.toBeInTheDocument();

    await user.keyboard("{Enter}");
    expect(screen.getByRole("status")).toHaveTextContent("ETHUSDT");
    expect(input).toHaveValue("ETHUSDT");
  });

  it("keeps accepting a manually entered value when no preset exists", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const input = screen.getByRole("combobox", { name: "合约代码" });
    await user.click(input);
    await user.type(input, "NEWTOKENUSDT");

    expect(screen.getByText("没有匹配项，可继续手动输入")).toBeInTheDocument();
    expect(input).toHaveValue("NEWTOKENUSDT");
  });
});
