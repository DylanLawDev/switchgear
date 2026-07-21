import { ButtonHTMLAttributes, forwardRef } from "react";
import styles from "./Button.module.css";

export type ButtonVariant = "default" | "primary" | "danger" | "ghost";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", className, type = "button", ...buttonProps },
  ref,
) {
  const cls = [styles.btn, styles[variant], className].filter(Boolean).join(" ");
  return <button ref={ref} type={type} className={cls} {...buttonProps} />;
});

export default Button;
