import { expect, it } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import InspectScope from "./InspectScope";

it("shows readable scope and keeps identifiers behind technical details", () => {
  renderWithProviders(
    <InspectScope
      scope={{
        user_id: "private-owner",
        folder_ids: ["folder-uuid"],
        filename: null,
        breadcrumbs: { "folder-uuid": ["cosm", "repositories", "c360-lead"] },
      }}
    />,
  );
  expect(
    screen.getByText(/1 eligible folder · All filenames/),
  ).toBeInTheDocument();
  expect(screen.queryByText(/private-owner/)).not.toBeInTheDocument();
  expect(screen.queryByText(/folder-uuid/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "View folders" }));
  expect(
    screen.getByText("cosm / repositories / c360-lead"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Technical details" }));
  expect(screen.getByTestId("inspect-code-content").textContent).toContain(
    "private-owner",
  );
});
