"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import ReviewView from "./ReviewView";

// /review/?id=5 - a query string (not /review/5) so the site can be exported as static files.
function ReviewRoute() {
  const id = Number(useSearchParams().get("id"));
  if (!id) return <div className="muted">No document selected.</div>;
  // key: a fresh form for each document when "Approve & next" moves on
  return <ReviewView key={id} id={id} />;
}

export default function ReviewPage() {
  return (
    <Suspense fallback={<div className="muted">Loading…</div>}>
      <ReviewRoute />
    </Suspense>
  );
}
