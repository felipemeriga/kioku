import { select, input } from "@inquirer/prompts";
import { brand, sym } from "./theme.js";

export async function selectAction<T>(
  message: string,
  choices: { name: string; value: T; description?: string }[],
): Promise<T> {
  return select<T>({
    message: brand.secondary(message),
    choices: choices.map((c) => ({ name: c.name, value: c.value, description: c.description })),
    theme: { prefix: brand.primary(sym.arrow) },
  });
}

export async function promptText(message: string, opts?: { default?: string }): Promise<string> {
  return input({ message: brand.secondary(message), default: opts?.default });
}
