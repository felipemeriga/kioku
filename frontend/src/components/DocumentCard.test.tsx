// frontend/src/components/DocumentCard.test.tsx
import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import DocumentCard from "./DocumentCard";

const mockDoc = {
  source_filename: "report.pdf",
  source_type: "pdf",
  has_file: true,
  chunks: 24,
  status: "completed" as const,
  created_at: new Date().toISOString(),
  folder_id: null,
};

describe("DocumentCard", () => {
  it("shows the real updated timestamp and supports keyboard file opening in a list", () => {
    const open = vi.fn();
    renderWithProviders(
      <DocumentCard
        variant="list"
        doc={{ ...mockDoc, last_updated: "2026-10-23T12:00:00Z" }}
        onDelete={vi.fn()}
        onDownload={vi.fn()}
        onOpen={open}
      />
    );
    expect(screen.getAllByText("PDF").length).toBeGreaterThan(0);
    expect(document.querySelector("time")?.dateTime).toBe(
      "2026-10-23T12:00:00Z"
    );
    fireEvent.keyDown(screen.getByRole("row"), { key: "Enter" });
    expect(open).toHaveBeenCalledWith("report.pdf");
  });

  it("renders filename", () => {
    renderWithProviders(
      <DocumentCard doc={mockDoc} onDelete={vi.fn()} onDownload={vi.fn()} />
    );
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
  });

  it("renders chunk count", () => {
    renderWithProviders(
      <DocumentCard doc={mockDoc} onDelete={vi.fn()} onDownload={vi.fn()} />
    );
    expect(screen.getByText(/24 chunks/)).toBeInTheDocument();
  });

  it("renders status chip", () => {
    renderWithProviders(
      <DocumentCard
        doc={{ ...mockDoc, status: "processing" }}
        onDelete={vi.fn()}
        onDownload={vi.fn()}
      />
    );
    expect(screen.getByText("processing")).toBeInTheDocument();
  });

  it("renders completed status", () => {
    renderWithProviders(
      <DocumentCard doc={mockDoc} onDelete={vi.fn()} onDownload={vi.fn()} />
    );
    expect(screen.getByText("completed")).toBeInTheDocument();
  });
});
