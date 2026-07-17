import { render, type RenderOptions } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import { CssBaseline } from "@mui/material";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";
import theme from "../theme";
import ToastProvider from "../components/ToastProvider";

interface Options extends Omit<RenderOptions, "wrapper"> {
  initialEntries?: string[];
}

export function renderWithProviders(
  ui: ReactElement,
  { initialEntries = ["/"], ...options }: Options = {}
) {
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <MemoryRouter initialEntries={initialEntries}>
        <ThemeProvider theme={theme}>
          <CssBaseline />
          <ToastProvider>{children}</ToastProvider>
        </ThemeProvider>
      </MemoryRouter>
    );
  }

  return render(ui, { wrapper: Wrapper, ...options });
}
