import React, { useEffect } from "react";

export default function Toast({ message, onDismiss, duration = 2200 }) {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(onDismiss, duration);
    return () => clearTimeout(t);
  }, [message, onDismiss, duration]);

  if (!message) return null;
  return (
    <div className="toast" data-testid="toast" role="status" aria-live="polite">
      {message}
    </div>
  );
}
