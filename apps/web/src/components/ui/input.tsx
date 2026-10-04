import * as React from "react";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  rightAction?: React.ReactNode;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className = "", label, error, rightAction, id, type, ...props }, ref) => {
    const generatedId = React.useId();
    const inputId = id || generatedId;

    return (
      <div className="w-full space-y-1.5">
        {(label || rightAction) && (
          <div className="flex items-center justify-between text-xs font-medium text-zinc-700">
            {label && <label htmlFor={inputId}>{label}</label>}
            {rightAction}
          </div>
        )}
        <input
          id={inputId}
          type={type}
          ref={ref}
          className={`w-full rounded-md border bg-white px-3 py-2 text-base sm:text-sm text-zinc-900 placeholder:text-zinc-400 transition-colors focus:outline-none focus:ring-1 ${
            error
              ? "border-red-500 focus:border-red-500 focus:ring-red-500"
              : "border-zinc-300 focus:border-zinc-900 focus:ring-zinc-900"
          } ${className}`}
          {...props}
        />
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>
    );
  }
);

Input.displayName = "Input";
