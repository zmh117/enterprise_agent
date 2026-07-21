import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions, type RenderResult } from "@testing-library/react";
import type { PropsWithChildren, ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

function Providers({ children, path = "/" }: PropsWithChildren<{ path?: string }>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>{children}</MemoryRouter></QueryClientProvider>;
}

export function renderWithProviders(ui: ReactElement, options: RenderOptions & { path?: string } = {}): RenderResult {
  const { path, ...renderOptions } = options;
  return render(ui, { wrapper: ({ children }) => <Providers path={path}>{children}</Providers>, ...renderOptions });
}
