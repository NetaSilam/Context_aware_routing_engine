type LogoVariant = "light" | "dark";

const LOGO_SRC: Record<LogoVariant, string> = {
  light: "/brand/logo-light.png",
  dark: "/brand/logo-dark.png",
};

const DEFAULT_HEIGHT: Record<LogoVariant, number> = {
  light: 64,
  dark: 40,
};

interface LogoProps {
  variant?: LogoVariant;
  height?: number;
  className?: string;
}

export default function Logo(props: LogoProps): JSX.Element {
  const variant = props.variant ?? "light";
  const height = props.height ?? DEFAULT_HEIGHT[variant];
  return (
    <img
      className={`brand-logo brand-logo--${variant} ${props.className ?? ""}`.trim()}
      src={LOGO_SRC[variant]}
      alt="Sa Bracha — context-aware safe routing"
      height={height}
    />
  );
}
