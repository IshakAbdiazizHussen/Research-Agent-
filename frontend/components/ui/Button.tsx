import type { ButtonHTMLAttributes } from "react";

type ButtonVariant = "primary" | "secondary";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export function Button({ variant = "primary", className, ...props }: ButtonProps) {
  return (
    <button
      {...props}
      className={["btn", variant === "primary" ? "btn-primary" : "btn-secondary", className]
        .filter(Boolean)
        .join(" ")}
    />
  );
}
