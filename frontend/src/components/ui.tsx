import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";

export function Card({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto mt-16 w-full max-w-md rounded-xl border bg-white p-6 shadow-sm">
      {children}
    </div>
  );
}

type FieldProps = InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string };

export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field(
  { label, error, ...props },
  ref,
) {
  return (
    <label className="mb-4 block text-sm">
      <span className="mb-1 block text-slate-600">{label}</span>
      <input
        ref={ref}
        className="w-full rounded-md border px-3 py-2 outline-none focus:border-slate-900"
        {...props}
      />
      {error ? <span className="mt-1 block text-red-600">{error}</span> : null}
    </label>
  );
});

export function Button(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className="w-full break-words rounded-md bg-slate-900 px-4 py-2 text-white disabled:opacity-50"
      {...props}
    />
  );
}
