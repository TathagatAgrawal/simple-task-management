// The page's own yes/no question, used instead of the browser's pop-up for anything that can't
// be undone. It names what will happen, and the safe answer is the one that has focus.
import { useEffect, useRef } from "preact/hooks";
import { answerConfirm, confirmRequest } from "../state";

export function ConfirmDialog() {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const request = confirmRequest.value;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (request && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal();
    }
    if (!request && dialog.open) dialog.close();
  }, [request]);

  return (
    <dialog
      ref={ref}
      class="modal confirm"
      aria-labelledby="confirm-title"
      aria-describedby="confirm-body"
      // Escape or a tap outside is "no".
      onCancel={() => answerConfirm(false)}
      onClose={() => {
        if (confirmRequest.value) answerConfirm(false);
        const from = opener.current as HTMLElement | null;
        if (from?.isConnected) from.focus();
      }}
    >
      {request && (
        <>
          <h2 id="confirm-title">{request.title}</h2>
          <p id="confirm-body" class="muted">
            {request.body}
          </p>
          <div class="row end confirm-actions">
            <button type="button" class="btn" autofocus onClick={() => answerConfirm(false)}>
              {request.cancelLabel}
            </button>
            <button type="button" class={`btn ${request.danger ? "danger-fill" : "primary"}`} onClick={() => answerConfirm(true)}>
              {request.confirmLabel}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
