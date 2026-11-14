import { allowedClearVariable, allowedVariable } from "./rootAccess";
import type { AccessCredential, UsageDelivery } from "./rootAccess";
export function usageFields(delivery: UsageDelivery): string[] {
  switch (delivery.kind) {
    case "env":
      return [...new Set(Object.values(delivery.field_mapping))];
    case "argv":
      return [
        ...new Set(
          delivery.arguments.flatMap((a) =>
            a.kind === "field" ? [a.field] : []
          )
        ),
      ];
    case "file":
      return [...new Set(delivery.patches.map((p) => p.field))];
    case "ssh":
      return [
        delivery.private_key_field,
        ...(delivery.passphrase_field ? [delivery.passphrase_field] : []),
      ];
  }
}
export function usageCapabilities(delivery: UsageDelivery): string[] {
  return delivery.kind === "argv"
    ? ["argv", "raw_secret_argv"]
    : [delivery.kind];
}
export function usageError(
  delivery: UsageDelivery,
  credential: AccessCredential
): string {
  const fields = usageFields(delivery);
  if (!fields.length || fields.some((f) => !credential.fields.includes(f)))
    return "Choose fields from this credential.";
  if (credential.kind === "aws" && !["env", "file"].includes(delivery.kind))
    return "AWS credentials use environment variables or a temporary configuration file.";
  if (delivery.kind === "env") {
    if (
      Object.keys(delivery.field_mapping).length > 32 ||
      Object.keys(delivery.field_mapping).some((n) => !allowedVariable(n))
    )
      return "Use up to 32 allowed environment variable names.";
    if (
      delivery.clear_env.length > 32 ||
      delivery.clear_env.some((n) => !allowedClearVariable(n))
    )
      return "Check the inherited variable names.";
    if (
      credential.kind === "aws" &&
      (delivery.field_mapping.AWS_ACCESS_KEY_ID !== "access_key_id" ||
        delivery.field_mapping.AWS_SECRET_ACCESS_KEY !== "secret_access_key")
    )
      return "Map both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY.";
  }
  if (delivery.kind === "argv") {
    if (!delivery.allow_raw_secret_argv)
      return "Acknowledge that raw secret arguments can appear in process lists.";
    if (
      delivery.arguments.length > 64 ||
      delivery.arguments.some(
        (a) =>
          a.kind === "literal" &&
          (!a.value || a.value.includes("\0") || a.value.length > 4096)
      )
    )
      return "Use up to 64 valid arguments.";
  }
  if (delivery.kind === "file") {
    if (
      !delivery.source_template.trim() ||
      delivery.source_template.length > 65536
    )
      return "Enter a nonsecret template, up to 64 KiB.";
    if (delivery.format === "json") {
      try {
        JSON.parse(delivery.source_template);
      } catch {
        return "Enter a valid JSON template.";
      }
    }
    if (
      !delivery.patches.length ||
      delivery.patches.length > 32 ||
      delivery.patches.some(
        (p) =>
          !p.path.length ||
          p.path.some(
            (k) =>
              !k || ["__proto__", "constructor", "prototype", ".."].includes(k)
          )
      )
    )
      return "Use key paths without traversal or unsafe keys.";
    if (
      delivery.destination.kind === "env"
        ? !(
            allowedVariable(delivery.destination.name) ||
            (credential.kind === "aws" &&
              delivery.destination.name === "AWS_SHARED_CREDENTIALS_FILE")
          )
        : !/^--[A-Za-z][A-Za-z0-9-]{0,100}$/.test(delivery.destination.name)
    )
      return "Use an allowed variable or a --config-style argument for the temporary file path.";
  }
  if (delivery.kind === "ssh") {
    if (
      !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$/.test(delivery.host) ||
      !/^[A-Za-z_][A-Za-z0-9_.-]{0,63}$/.test(delivery.user) ||
      !Number.isInteger(delivery.port) ||
      delivery.port < 1 ||
      delivery.port > 65535
    )
      return "Enter a valid SSH host, user and port.";
    if (
      !/^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) [A-Za-z0-9+/]+={0,3}$/.test(
        delivery.host_key
      )
    )
      return "Pin the trusted SSH public host key (type and base64).";
    if (credential.kind !== "ssh") return "Select an SSH key credential.";
  }
  return "";
}

export function usagePreview(delivery: UsageDelivery): string {
  switch (delivery.kind) {
    case "env":
      return Object.entries(delivery.field_mapping)
        .map(([variable, field]) => `${variable} ← credential.${field}`)
        .join("\n");
    case "file":
      return (
        `${delivery.format.toUpperCase()} temporary file → ${
          delivery.destination.kind
        }: ${delivery.destination.name}\n` +
        delivery.patches
          .map((p) => `${p.path.join(".")} ← credential.${p.field}`)
          .join("\n")
      );
    case "argv":
      return delivery.arguments
        .map((arg) =>
          arg.kind === "literal" ? arg.value : `credential.${arg.field}`
        )
        .join(" ");
    case "ssh":
      return `${delivery.user}@${delivery.host}:${delivery.port}\nPinned host key: ${delivery.host_key}\nIdentity: credential.${delivery.private_key_field}`;
  }
}
