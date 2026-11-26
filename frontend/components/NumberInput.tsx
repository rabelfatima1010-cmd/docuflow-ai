"use client";

import { useEffect, useState } from "react";

/** Text box for money/quantity values that lets people type freely ("1801.", "0.5", "-")
 *  and only reports a number once the text is a valid one. A plain controlled input that
 *  re-renders Number(text) drops a trailing "." and makes decimals impossible to type. */
export function NumberInput({
  value,
  onChange,
  className,
  allowEmpty = true,
}: {
  value: number | null;
  onChange: (v: number | null) => void;
  className?: string;
  allowEmpty?: boolean;
}) {
  const [text, setText] = useState(value == null ? "" : String(value));

  // Follow outside changes (e.g. a reload), but not while the text already means the same number
  useEffect(() => {
    setText((t) => (parse(t) === value ? t : value == null ? "" : String(value)));
  }, [value]);

  return (
    <input
      className={className}
      inputMode="decimal"
      value={text}
      onChange={(e) => {
        const t = e.target.value.replace(/,/g, "");
        if (!/^-?\d*\.?\d*$/.test(t)) return; // ignore letters
        setText(t);
        const n = parse(t);
        if (n !== undefined) onChange(n);
        else if (t === "") onChange(allowEmpty ? null : 0);
      }}
      onBlur={() => setText(value == null ? "" : String(value))}
    />
  );
}

function parse(t: string): number | null | undefined {
  if (t.trim() === "") return null;
  if (t === "-" || t === "." || t === "-.") return undefined;
  const n = Number(t);
  return Number.isFinite(n) ? n : undefined;
}
