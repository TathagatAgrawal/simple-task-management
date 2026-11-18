// A native <dialog> that opens when the shared ``modal`` signal names it. Phones show it as a
// bottom sheet (CSS) that can be dragged down to dismiss (gestures.ts).
import type { ComponentChildren } from "preact";
import { useEffect, useRef } from "preact/hooks";
import { dismissGesture } from "../gestures";
import { type ModalName, modal } from "../state";

export function Modal({
  name,
  wide,
  children,
}: {
  name: ModalName;
  wide?: boolean;
  children: ComponentChildren;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const open = modal.value === name;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const stop = dismissGesture(dialog, "y", (e) => !!(e.target as Element).closest(".sheet-grab, h2"));
    const tapAbove = (e: MouseEvent) => {
      const r = dialog.getBoundingClientRect();
      if (window.matchMedia("(max-width: 640px)").matches && e.target === dialog && e.clientY < r.top) {
        dialog.close();
      }
    };
    dialog.addEventListener("click", tapAbove);
    return () => {
      stop();
      dialog.removeEventListener("click", tapAbove);
    };
  }, []);

  return (
    <dialog
      ref={ref}
      class={`modal${wide ? " wide" : ""}`}
      onClose={() => {
        if (modal.value === name) modal.value = null;
      }}
    >
      <div class="sheet-grab" aria-hidden="true" />
      {open && children}
    </dialog>
  );
}

/** A "Close" / "Done" button for the foot of a dialog. */
export function CloseButton({ label }: { label: string }) {
  return (
    <div class="row end">
      <button class="btn" type="button" onClick={() => (modal.value = null)}>
        {label}
      </button>
    </div>
  );
}
